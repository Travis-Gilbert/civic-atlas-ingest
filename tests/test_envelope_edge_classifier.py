from __future__ import annotations

from civic_atlas_ingest.envelope_edge_classifier import classify_cardinal_edges_by_roads

RECTANGLE = {
    "type": "Polygon",
    "coordinates": [
        [
            [-83.7000, 43.0000],
            [-83.6988, 43.0000],
            [-83.6988, 43.0009],
            [-83.7000, 43.0009],
            [-83.7000, 43.0000],
        ]
    ],
}


def test_classify_cardinal_edges_by_nearest_south_road() -> None:
    road = {
        "type": "LineString",
        "coordinates": [[-83.7002, 42.9999], [-83.6986, 42.9999]],
    }

    edges = classify_cardinal_edges_by_roads(
        parcel_geometry=RECTANGLE,
        road_geometries=(road,),
    )

    assert edges.front == "south"
    assert edges.rear == "north"
    assert edges.is_corner is False


def test_classify_cardinal_edges_flags_corner_lot() -> None:
    south_road = {
        "type": "LineString",
        "coordinates": [[-83.7002, 42.9999], [-83.6986, 42.9999]],
    }
    west_road = {
        "type": "LineString",
        "coordinates": [[-83.70015, 42.9999], [-83.70015, 43.0010]],
    }

    edges = classify_cardinal_edges_by_roads(
        parcel_geometry=RECTANGLE,
        road_geometries=(south_road, west_road),
        corner_tolerance_m=20.0,
    )

    assert edges.front == "south"
    assert edges.secondary_front == "west"
    assert edges.is_corner is True
