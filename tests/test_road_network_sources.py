from __future__ import annotations

from datetime import UTC, datetime

from civic_atlas_ingest.road_network_sources import (
    FLINT_OSM_PLACE_QUERY,
    build_road_network_snapshot,
    fetch_osmnx_road_geometries,
)


class FakeGeometrySeries(list[object]):
    def dropna(self) -> FakeGeometrySeries:
        return FakeGeometrySeries(item for item in self if item is not None)


class FakeEdges:
    geometry = FakeGeometrySeries(
        [
            {
                "type": "LineString",
                "coordinates": [[-83.7, 43.0], [-83.699, 43.0]],
            },
            {
                "type": "MultiLineString",
                "coordinates": (
                    ((-83.7, 43.001), (-83.699, 43.001)),
                    ((-83.698, 43.001), (-83.697, 43.001)),
                ),
            },
            None,
            {"type": "LineString", "coordinates": []},
        ]
    )


class FakeGraph:
    pass


class FakeGraphApi:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def graph_from_place(self, place_query: str, **kwargs: object) -> FakeGraph:
        self.calls.append({"place_query": place_query, **kwargs})
        return FakeGraph()


class FakeConvertApi:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def graph_to_gdfs(self, graph: FakeGraph, **kwargs: object) -> FakeEdges:
        self.calls.append({"graph": graph, **kwargs})
        return FakeEdges()


class FakeOsmnx:
    def __init__(self) -> None:
        self.graph = FakeGraphApi()
        self.convert = FakeConvertApi()


def test_fetch_osmnx_road_geometries_returns_normalized_linestrings() -> None:
    fake_osmnx = FakeOsmnx()

    roads = fetch_osmnx_road_geometries(osmnx_module=fake_osmnx)

    assert fake_osmnx.graph.calls == [
        {
            "place_query": FLINT_OSM_PLACE_QUERY,
            "network_type": "drive",
            "simplify": True,
            "retain_all": False,
            "truncate_by_edge": True,
        }
    ]
    assert fake_osmnx.convert.calls[0]["nodes"] is False
    assert fake_osmnx.convert.calls[0]["fill_edge_geometry"] is True
    assert roads == (
        {
            "type": "LineString",
            "coordinates": [[-83.7, 43.0], [-83.699, 43.0]],
        },
        {
            "type": "LineString",
            "coordinates": [[-83.7, 43.001], [-83.699, 43.001]],
        },
        {
            "type": "LineString",
            "coordinates": [[-83.698, 43.001], [-83.697, 43.001]],
        },
    )


def test_build_road_network_snapshot_hashes_stable_road_content() -> None:
    roads = (
        {
            "type": "LineString",
            "coordinates": [[-83.7, 43.0], [-83.699, 43.0]],
        },
    )
    first = build_road_network_snapshot(
        road_geometries=roads,
        retrieved_at=datetime(2026, 5, 22, tzinfo=UTC),
    )
    second = build_road_network_snapshot(
        road_geometries=roads,
        retrieved_at=datetime(2026, 5, 23, tzinfo=UTC),
    )

    assert first.source_key == "flint-osm-road-network-drive"
    assert first.source_label == "OpenStreetMap road network via OSMnx"
    assert first.road_count == 1
    assert first.content_sha256 == second.content_sha256
    assert first.retrieved_at != second.retrieved_at
