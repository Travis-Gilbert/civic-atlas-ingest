"""Smoke tests for the Sanborn vectorizer pipeline.

These tests build a SYNTHETIC Sanborn sheet — a small RGB raster
with hand-placed colored rectangles in Sanborn-canonical colors —
so the test exercises the full color-decode → vectorize → georef
pipeline without depending on a real LoC scan being available on
the test runner.

The synthetic sheet is also a useful reference for what good
Sanborn-style input looks like to the decoder, which helps future
calibration work on real scans.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PIL", reason="Sanborn pipeline tests need Pillow")
pytest.importorskip("rasterio", reason="Sanborn pipeline tests need rasterio")


def test_color_decoder_separates_canonical_colors():
    """Each Sanborn-canonical color should land in its own bucket."""
    from civic_atlas_ingest.sanborn_color_decoder import (
        MaterialCode,
        classify_pixels,
    )

    # 5×N stripes, each a different canonical material color.
    # Colors picked to land confidently inside DEFAULT_BANDS.
    canvas = np.full((50, 250, 3), 245, dtype=np.uint8)  # paper background
    canvas[:, 0:50] = (240, 220, 80)  # yellow → wood frame
    canvas[:, 50:100] = (230, 100, 120)  # pink → brick
    canvas[:, 100:150] = (80, 110, 200)  # blue → stone
    canvas[:, 150:200] = (130, 130, 130)  # gray → iron
    canvas[:, 200:250] = (140, 90, 50)  # brown → adobe

    classified = classify_pixels(canvas)

    # Check the dominant material in each stripe matches expectation.
    expected_per_stripe = [
        (0, 50, MaterialCode.WOOD_FRAME),
        (50, 100, MaterialCode.BRICK),
        (100, 150, MaterialCode.STONE),
        (150, 200, MaterialCode.IRON),
        (200, 250, MaterialCode.ADOBE),
    ]
    for x0, x1, expected in expected_per_stripe:
        stripe = classified[:, x0:x1]
        # Center pixels (away from stripe borders) should be the
        # expected material.
        center = stripe[20:30, (x1 - x0) // 2]
        assert (center == int(expected)).all(), (
            f"stripe [{x0}:{x1}] expected {expected.name} but got {center.tolist()}"
        )


def test_vectorizer_extracts_polygons_from_synthetic_sheet():
    """A synthetic sheet with three building rectangles should
    yield three polygons of the right materials."""
    from civic_atlas_ingest.sanborn_color_decoder import (
        MaterialCode,
        classify_pixels,
    )
    from civic_atlas_ingest.sanborn_vectorize import extract_polygons

    canvas = np.full((200, 200, 3), 245, dtype=np.uint8)
    # Three rectangles, well-separated so they don't merge.
    canvas[20:60, 20:60] = (240, 220, 80)  # wood frame ~ 1600 px
    canvas[20:80, 100:160] = (230, 100, 120)  # brick ~ 3600 px
    canvas[120:180, 60:140] = (80, 110, 200)  # stone ~ 4800 px

    classified = classify_pixels(canvas)
    polygons = extract_polygons(classified, min_area_px=200)

    assert len(polygons) == 3
    materials = {p.material for p in polygons}
    assert materials == {
        MaterialCode.WOOD_FRAME,
        MaterialCode.BRICK,
        MaterialCode.STONE,
    }
    # Areas should approximate the rectangles' pixel counts.
    by_material = {p.material: p.area_pixels for p in polygons}
    assert 1400 < by_material[MaterialCode.WOOD_FRAME] < 1800
    assert 3400 < by_material[MaterialCode.BRICK] < 3800
    assert 4600 < by_material[MaterialCode.STONE] < 5000


def test_georef_bbox_round_trip(tmp_path):
    """A 100×100 sheet with a known bbox should round-trip pixel↔geo cleanly."""
    from civic_atlas_ingest.sanborn_georef import parse_georeference

    # Make a tiny PNG so the georef module can read its dims.
    from PIL import Image

    image_path = tmp_path / "synthetic.png"
    Image.fromarray(np.full((100, 100, 3), 245, dtype=np.uint8)).save(image_path)

    payload = {
        "image_path": "synthetic.png",
        "sheet_id": "test-1925-00",
        "year": 1925,
        "source": "synthetic",
        "format": "bbox",
        "bbox": {
            "north": 43.02,
            "south": 43.00,
            "east": -83.69,
            "west": -83.71,
        },
    }

    georef = parse_georeference(payload, base_dir=tmp_path)
    # Top-left pixel should map to north + west.
    lng, lat = georef.to_world(0.0, 0.0)
    assert abs(lat - 43.02) < 1e-6
    assert abs(lng + 83.71) < 1e-6
    # Bottom-right pixel should map to south + east.
    lng, lat = georef.to_world(100.0, 100.0)
    assert abs(lat - 43.00) < 1e-6
    assert abs(lng + 83.69) < 1e-6
    # Inverse round-trip.
    px, py = georef.to_pixel(-83.70, 43.01)
    assert abs(px - 50.0) < 1e-3
    assert abs(py - 50.0) < 1e-3


def test_polygon_transform_to_world(tmp_path):
    """A pixel-space polygon should transform to lat/lng cleanly."""
    from PIL import Image
    from shapely.geometry import Polygon

    from civic_atlas_ingest.sanborn_georef import parse_georeference, transform_polygon

    image_path = tmp_path / "synthetic.png"
    Image.fromarray(np.full((100, 100, 3), 245, dtype=np.uint8)).save(image_path)

    georef = parse_georeference(
        {
            "image_path": "synthetic.png",
            "sheet_id": "test-1925-00",
            "year": 1925,
            "source": "synthetic",
            "bbox": {
                "north": 43.02,
                "south": 43.00,
                "east": -83.69,
                "west": -83.71,
            },
        },
        base_dir=tmp_path,
    )

    # 20x20 pixel polygon centered at (50, 50).
    poly = Polygon([(40, 40), (60, 40), (60, 60), (40, 60), (40, 40)])
    geo = transform_polygon(poly, georef)
    assert geo["type"] == "Polygon"
    ring = geo["coordinates"][0]
    # Four corners + closing point.
    assert len(ring) == 5
    # All four world coords should be inside the sheet's bbox.
    for lng, lat in ring:
        assert -83.71 <= lng <= -83.69
        assert 43.00 <= lat <= 43.02


def test_control_point_georef_fits_affine(tmp_path):
    """A four-control-point affine should match the same bbox transform."""
    from PIL import Image

    from civic_atlas_ingest.sanborn_georef import parse_georeference

    image_path = tmp_path / "synthetic.png"
    Image.fromarray(np.full((100, 100, 3), 245, dtype=np.uint8)).save(image_path)

    payload = {
        "image_path": "synthetic.png",
        "sheet_id": "test-cp",
        "year": 1925,
        "source": "synthetic",
        "format": "control_points",
        "control_points": [
            [0, 0, -83.71, 43.02],
            [100, 0, -83.69, 43.02],
            [0, 100, -83.71, 43.00],
            [100, 100, -83.69, 43.00],
        ],
    }
    georef = parse_georeference(payload, base_dir=tmp_path)
    lng, lat = georef.to_world(50.0, 50.0)
    assert abs(lng + 83.70) < 1e-4
    assert abs(lat - 43.01) < 1e-4
