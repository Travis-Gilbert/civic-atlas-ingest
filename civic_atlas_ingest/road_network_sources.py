"""Road-network snapshot helpers for zoning envelope edge classification."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FLINT_OSM_PLACE_QUERY = "Flint, Michigan, USA"
DEFAULT_NETWORK_TYPE = "drive"
OSM_SOURCE_LABEL = "OpenStreetMap road network via OSMnx"


@dataclass(frozen=True)
class RoadNetworkSnapshot:
    city_pack: str
    source_key: str
    source_label: str
    place_query: str
    network_type: str
    retrieved_at: str
    road_count: int
    content_sha256: str
    road_geometries: tuple[dict[str, object], ...]
    metadata: dict[str, object]


def fetch_osmnx_road_geometries(
    *,
    place_query: str = FLINT_OSM_PLACE_QUERY,
    network_type: str = DEFAULT_NETWORK_TYPE,
    simplify: bool = True,
    retain_all: bool = False,
    truncate_by_edge: bool = True,
    buffer_dist_m: float | None = None,
    osmnx_module: Any | None = None,
) -> tuple[dict[str, object], ...]:
    """Fetch OSM road edge geometries as GeoJSON LineStrings.

    The optional ``osmnx_module`` argument keeps tests deterministic and lets
    Ray/RunPod workers own the heavy OSMnx dependency at runtime.
    """
    ox = osmnx_module if osmnx_module is not None else _import_osmnx()
    graph_kwargs = {
        "network_type": network_type,
        "simplify": simplify,
        "retain_all": retain_all,
        "truncate_by_edge": truncate_by_edge,
    }
    graph_from_place_signature = inspect.signature(ox.graph.graph_from_place)
    if buffer_dist_m is not None:
        if "buffer_dist" not in graph_from_place_signature.parameters:
            raise ValueError("buffer_dist_m is not supported by this OSMnx graph_from_place API")
        graph_kwargs["buffer_dist"] = buffer_dist_m
    graph = ox.graph.graph_from_place(place_query, **graph_kwargs)
    edges_gdf = ox.convert.graph_to_gdfs(graph, nodes=False, fill_edge_geometry=True)
    return _road_geometries_from_edges(edges_gdf)


def build_road_network_snapshot(
    *,
    road_geometries: tuple[dict[str, object], ...],
    city_pack: str = "flint",
    place_query: str = FLINT_OSM_PLACE_QUERY,
    network_type: str = DEFAULT_NETWORK_TYPE,
    retrieved_at: datetime | None = None,
) -> RoadNetworkSnapshot:
    retrieved = retrieved_at or datetime.now(UTC)
    stable_content = _stable_json(
        {
            "place_query": place_query,
            "network_type": network_type,
            "road_geometries": road_geometries,
        }
    )
    content_sha256 = hashlib.sha256(stable_content.encode()).hexdigest()
    return RoadNetworkSnapshot(
        city_pack=city_pack,
        source_key=f"{city_pack}-osm-road-network-{network_type}",
        source_label=OSM_SOURCE_LABEL,
        place_query=place_query,
        network_type=network_type,
        retrieved_at=retrieved.isoformat(),
        road_count=len(road_geometries),
        content_sha256=content_sha256,
        road_geometries=road_geometries,
        metadata={
            "fetcher": "osmnx.graph.graph_from_place",
            "converter": "osmnx.convert.graph_to_gdfs",
            "geometry_type": "LineString",
            "source_boundary": "public OpenStreetMap data fetched through OSMnx",
        },
    )


def write_flint_road_network_snapshot(
    output_path: Path,
    *,
    place_query: str = FLINT_OSM_PLACE_QUERY,
    network_type: str = DEFAULT_NETWORK_TYPE,
    buffer_dist_m: float | None = None,
) -> RoadNetworkSnapshot:
    road_geometries = fetch_osmnx_road_geometries(
        place_query=place_query,
        network_type=network_type,
        buffer_dist_m=buffer_dist_m,
    )
    snapshot = build_road_network_snapshot(
        road_geometries=road_geometries,
        place_query=place_query,
        network_type=network_type,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asdict(snapshot), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return snapshot


def _import_osmnx() -> Any:
    try:
        import osmnx as ox
    except ImportError as exc:
        raise RuntimeError(
            "OSMnx is required to fetch live road-network snapshots. "
            "Install the civic-atlas-ingest geospatial dependencies before running this job."
        ) from exc
    return ox


def _road_geometries_from_edges(edges_gdf: Any) -> tuple[dict[str, object], ...]:
    geometries = getattr(edges_gdf, "geometry", ())
    if hasattr(geometries, "dropna"):
        geometries = geometries.dropna()

    roads: list[dict[str, object]] = []
    for geometry in geometries:
        try:
            roads.extend(_line_geometries_from_geo_interface(geometry))
        except ValueError:
            continue
    if not roads:
        raise ValueError("road snapshot did not contain any usable LineString geometries")
    return tuple(roads)


def _line_geometries_from_geo_interface(geometry: Any) -> tuple[dict[str, object], ...]:
    geojson = (
        geometry
        if isinstance(geometry, dict)
        else getattr(geometry, "__geo_interface__", None)
    )
    if not isinstance(geojson, dict):
        raise ValueError("road geometry must expose a GeoJSON interface")

    geometry_type = geojson.get("type")
    coordinates = geojson.get("coordinates")
    if geometry_type == "LineString":
        return (_normalize_linestring(coordinates),)
    if geometry_type == "MultiLineString":
        if not isinstance(coordinates, list | tuple):
            raise ValueError("MultiLineString coordinates must be a list or tuple")
        return tuple(_normalize_linestring(line) for line in coordinates)
    raise ValueError(f"unsupported road geometry type: {geometry_type}")


def _normalize_linestring(coordinates: object) -> dict[str, object]:
    if not isinstance(coordinates, list | tuple) or len(coordinates) < 2:
        raise ValueError("LineString coordinates must contain at least two positions")

    normalized: list[list[float]] = []
    for position in coordinates:
        if not isinstance(position, list | tuple) or len(position) < 2:
            raise ValueError("LineString positions must contain lon and lat")
        normalized.append([float(position[0]), float(position[1])])
    return {"type": "LineString", "coordinates": normalized}


def _stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Snapshot Flint OSM roads for envelope setbacks.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("city_packs/flint/zoning/road-network-current.json"),
    )
    parser.add_argument("--place-query", default=FLINT_OSM_PLACE_QUERY)
    parser.add_argument("--network-type", default=DEFAULT_NETWORK_TYPE)
    parser.add_argument("--buffer-dist-m", type=float, default=None)
    args = parser.parse_args()

    snapshot = write_flint_road_network_snapshot(
        args.output,
        place_query=args.place_query,
        network_type=args.network_type,
        buffer_dist_m=args.buffer_dist_m,
    )
    print(f"wrote {snapshot.road_count} roads to {args.output}")


if __name__ == "__main__":
    main()
