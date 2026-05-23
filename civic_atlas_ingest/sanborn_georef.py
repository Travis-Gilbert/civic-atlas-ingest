"""Pixel ↔ geographic coordinate transform for Sanborn sheets.

Sanborn sheets are raster images with no inherent georeferencing.
To consume them in the corpus, each sheet needs a pixel-to-geo
transform. This module supports two common input formats:

  1. **Sheet bounding box** (simplest, accurate enough for hand-aligned
     Carriage Town sheets): four numbers — the lat/lng of the
     north, south, east, west edges of the image. Assumes the image
     is axis-aligned (north is up, no rotation). Yields an affine
     transform via simple scale + translate.

  2. **Control points** (more accurate, supports rotation/skew):
     a list of (pixel_x, pixel_y, lng, lat) tuples — at least 3,
     ideally 6+ spread across the sheet. Computes a least-squares
     affine fit. Useful for sheets that were scanned slightly rotated
     or printed with non-cardinal orientation.

Either format is JSON-loadable. The shape spec lives in
`SheetGeoreference`. Example:

    {
      "image_path": "sanborn_flint_1925_sheet_03.tif",
      "format": "bbox",
      "bbox": { "north": 43.0148, "south": 43.0102,
                "east": -83.6911, "west": -83.6982 },
      "year": 1925,
      "sheet_id": "flint-1925-03",
      "source": "library_of_congress",
      "source_uri": "https://www.loc.gov/item/..."
    }

Or with control points:

    {
      "image_path": "sanborn_flint_1899_sheet_12.tif",
      "format": "control_points",
      "control_points": [
        [120, 80, -83.6982, 43.0148],   # px_x, px_y, lng, lat
        [4830, 80, -83.6911, 43.0148],
        [120, 6240, -83.6982, 43.0102],
        [4830, 6240, -83.6911, 43.0102]
      ],
      "year": 1899,
      "sheet_id": "flint-1899-12",
      "source": "umich_flint_gis_center"
    }

The pixel coordinate system follows raster convention: origin top-left,
x increases right, y increases DOWN.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class SheetGeoreference:
    """One Sanborn sheet's pixel-to-geo transform."""

    image_path: Path
    sheet_id: str
    year: int
    source: str
    source_uri: str | None
    # 6-parameter affine: [a, b, c, d, e, f] such that
    #   lng = a*px + b*py + c
    #   lat = d*px + e*py + f
    affine: tuple[float, float, float, float, float, float]
    image_width: int
    image_height: int

    def to_pixel(self, lng: float, lat: float) -> tuple[float, float]:
        """Inverse transform: world coords → pixel coords."""
        a, b, c, d, e, f = self.affine
        # Solve a 2x2 linear system. det = a*e - b*d.
        det = a * e - b * d
        if abs(det) < 1e-18:
            raise ValueError("affine is degenerate; cannot invert")
        dx = lng - c
        dy = lat - f
        px = (dx * e - dy * b) / det
        py = (dy * a - dx * d) / det
        return px, py

    def to_world(self, px: float, py: float) -> tuple[float, float]:
        """Forward transform: pixel coords → world coords (lng, lat)."""
        a, b, c, d, e, f = self.affine
        lng = a * px + b * py + c
        lat = d * px + e * py + f
        return lng, lat


def load_georeference(georef_path: Path) -> SheetGeoreference:
    """Load a SheetGeoreference from a JSON file.

    The JSON must contain `image_path` (relative to the JSON file's
    directory or absolute), `sheet_id`, `year`, `source`, and either
    a `bbox` block or a `control_points` list.
    """
    payload = json.loads(Path(georef_path).read_text())
    return parse_georeference(payload, base_dir=Path(georef_path).resolve().parent)


def parse_georeference(payload: dict[str, Any], *, base_dir: Path) -> SheetGeoreference:
    """Build a SheetGeoreference from a parsed JSON dict.

    Splits the bbox vs control-points formats. The image dimensions
    are read lazily from the file on disk so callers don't have to
    type the pixel size manually — but the image must exist.
    """
    required = {"image_path", "sheet_id", "year", "source"}
    missing = required - payload.keys()
    if missing:
        raise ValueError(f"georef payload missing required fields: {sorted(missing)}")

    image_path = Path(payload["image_path"])
    if not image_path.is_absolute():
        image_path = (base_dir / image_path).resolve()
    if not image_path.exists():
        raise FileNotFoundError(f"image_path does not resolve to a file: {image_path}")

    image_width, image_height = _read_image_dims(image_path)

    fmt = payload.get("format")
    if fmt is None:
        fmt = "bbox" if "bbox" in payload else "control_points"

    if fmt == "bbox":
        affine = _affine_from_bbox(payload["bbox"], image_width, image_height)
    elif fmt == "control_points":
        affine = _affine_from_control_points(payload["control_points"])
    else:
        raise ValueError(f"unknown georef format: {fmt!r}")

    return SheetGeoreference(
        image_path=image_path,
        sheet_id=str(payload["sheet_id"]),
        year=int(payload["year"]),
        source=str(payload["source"]),
        source_uri=payload.get("source_uri"),
        affine=affine,
        image_width=image_width,
        image_height=image_height,
    )


def transform_polygon(
    pixel_polygon: Any,
    georef: SheetGeoreference,
) -> dict[str, Any]:
    """Convert a shapely polygon in pixel space to a GeoJSON dict in
    EPSG:4326 (lng, lat) via the georeference's affine.

    Returns a GeoJSON Polygon dict ready to pass to `make_training_record`.
    """
    try:
        from shapely.geometry import Polygon  # noqa: F401  (validation)
    except ImportError as exc:
        raise RuntimeError("transform_polygon requires shapely") from exc

    ring = list(pixel_polygon.exterior.coords)
    geo_ring = [list(georef.to_world(px, py)) for px, py in ring]
    holes_geo = []
    for interior in pixel_polygon.interiors:
        hole = [list(georef.to_world(px, py)) for px, py in interior.coords]
        holes_geo.append(hole)
    coordinates = [geo_ring, *holes_geo]
    return {"type": "Polygon", "coordinates": coordinates}


# ── Internal helpers ────────────────────────────────────────────────


def _read_image_dims(path: Path) -> tuple[int, int]:
    """Return (width, height) without loading the full pixel data.

    Uses PIL because it lazy-reads the header for most formats
    (TIFF, PNG, JPEG). Avoids the full rasterio open for a width
    query, which would also read the GeoTIFF tags we don't need here.
    """
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("PIL/Pillow required for image dim reads") from exc
    with Image.open(path) as image:
        return int(image.width), int(image.height)


def _affine_from_bbox(
    bbox: dict[str, float],
    width: int,
    height: int,
) -> tuple[float, float, float, float, float, float]:
    """Build a 6-param affine from an axis-aligned sheet bounding box.

    Sanborn pixel convention: top-left origin, y increases down. So
    the top edge of the image is `north` lat, bottom is `south` lat.

      lng = (px / width) * (east - west) + west
          = (east - west) / width * px + 0 * py + west
      lat = -(py / height) * (north - south) + north
          = 0 * px + (south - north) / height * py + north
    """
    required = {"north", "south", "east", "west"}
    missing = required - bbox.keys()
    if missing:
        raise ValueError(f"bbox missing fields: {sorted(missing)}")
    north, south = float(bbox["north"]), float(bbox["south"])
    east, west = float(bbox["east"]), float(bbox["west"])
    if north <= south or east <= west:
        raise ValueError(
            "bbox must satisfy north > south and east > west "
            f"(got north={north}, south={south}, east={east}, west={west})"
        )
    a = (east - west) / max(1.0, float(width))
    b = 0.0
    c = west
    d = 0.0
    e = (south - north) / max(1.0, float(height))
    f = north
    return (a, b, c, d, e, f)


def _affine_from_control_points(
    points: list[list[float]],
) -> tuple[float, float, float, float, float, float]:
    """Least-squares affine fit from 3+ control points.

    Each control point is [pixel_x, pixel_y, lng, lat]. Solves for
    the (a, b, c, d, e, f) that minimizes sum of squared residuals
    on both lng and lat predictions.
    """
    if len(points) < 3:
        raise ValueError(
            f"need at least 3 control points for an affine fit; got {len(points)}"
        )

    px = np.array([p[0] for p in points], dtype=np.float64)
    py = np.array([p[1] for p in points], dtype=np.float64)
    lng = np.array([p[2] for p in points], dtype=np.float64)
    lat = np.array([p[3] for p in points], dtype=np.float64)

    # Design matrix: each row is [px, py, 1] for the (a, b, c) fit
    # against lng, and identically for the (d, e, f) fit against lat.
    A = np.stack([px, py, np.ones_like(px)], axis=1)

    # numpy.linalg.lstsq does the QR-based least-squares fit.
    (a, b, c), *_ = np.linalg.lstsq(A, lng, rcond=None)
    (d, e, f), *_ = np.linalg.lstsq(A, lat, rcond=None)
    return (float(a), float(b), float(c), float(d), float(e), float(f))
