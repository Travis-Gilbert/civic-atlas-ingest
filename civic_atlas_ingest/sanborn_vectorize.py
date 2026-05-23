"""Per-polygon vectorization for Sanborn sheets.

Takes a material-classified raster (output of
`sanborn_color_decoder.classify_pixels`), groups same-material
neighboring pixels into polygons, and emits one record per building
polygon with its dominant material.

Two stages:

  1. **Connected-component grouping**: scan the raster, build a set
     of connected same-material regions. Background and label
     pixels are dropped before this step so the labels don't bridge
     adjacent buildings.

  2. **Polygon extraction**: rasterio.features.shapes turns each
     connected component into a shapely Polygon (in pixel space).
     Small fragments (< MIN_POLYGON_AREA_PX) are filtered out — these
     are scanner noise, lot-line ticks, label glyph remainders.

The output is still in pixel space. `sanborn_georef.transform_polygon`
converts each polygon to lat/lng using the sheet's georeferencing.

Story-count OCR happens in a separate pass over the *original* RGB
image, sampling the polygon's interior to find printed digits. See
the optional `extract_story_count` function below — it's best-effort
with explicit graceful fallback when Tesseract isn't installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import numpy as np

from .sanborn_color_decoder import MaterialCode


MIN_POLYGON_AREA_PX = 200  # smaller fragments are noise / glyph remainders
MAX_POLYGON_AREA_PX = 1_000_000  # larger means we caught the whole block as one "polygon"


@dataclass(frozen=True)
class SanbornPolygonRecord:
    """One vectorized building polygon from a Sanborn sheet."""

    polygon_pixel: Any  # shapely.geometry.Polygon (in pixel coordinates)
    material: MaterialCode
    area_pixels: int
    bbox_pixel: tuple[float, float, float, float]  # (minx, miny, maxx, maxy)
    story_count: int | None = None  # populated by extract_story_count() if available


def extract_polygons(
    classified: np.ndarray,
    *,
    min_area_px: int = MIN_POLYGON_AREA_PX,
    max_area_px: int = MAX_POLYGON_AREA_PX,
    drop_materials: tuple[MaterialCode, ...] = (
        MaterialCode.BACKGROUND,
        MaterialCode.LABEL,
    ),
) -> list[SanbornPolygonRecord]:
    """Vectorize a material-classified raster into per-polygon records.

    `drop_materials` controls which classes are skipped during
    polygon extraction — typically BACKGROUND (the paper) and LABEL
    (text and lot lines). The remaining building-material classes
    each become one or more polygons.

    Returns a list of `SanbornPolygonRecord`, one per polygon that
    passes the size filter. Sorted by area_pixels descending so the
    largest (most-likely-real) buildings come first.
    """
    try:
        from rasterio import features
        from shapely.geometry import shape
    except ImportError as exc:
        raise RuntimeError(
            "extract_polygons requires rasterio + shapely. "
            "Install via `pip install -e '.[corpus]'` or the base deps."
        ) from exc

    if classified.ndim != 2:
        raise ValueError(f"expected (H, W) classified raster; got shape {classified.shape}")
    if classified.dtype != np.uint8:
        raise ValueError(f"expected uint8 classified raster; got {classified.dtype}")

    drop_set = {int(m) for m in drop_materials}
    # Mask out background + label pixels so polygon extraction
    # operates only on building-material pixels.
    mask = ~np.isin(classified, list(drop_set))
    # rasterio.features.shapes wants a uint8 raster; the mask
    # constrains which pixels participate.
    raster_for_shapes = np.where(mask, classified, 0).astype(np.uint8)

    records: list[SanbornPolygonRecord] = []
    for geom_dict, value in features.shapes(raster_for_shapes, mask=mask):
        material_int = int(value)
        if material_int in drop_set or material_int == 0:
            continue
        try:
            poly = shape(geom_dict)
        except (ValueError, TypeError):
            continue
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            continue
        area_px = int(poly.area)
        if area_px < min_area_px or area_px > max_area_px:
            continue
        minx, miny, maxx, maxy = poly.bounds
        records.append(
            SanbornPolygonRecord(
                polygon_pixel=poly,
                material=MaterialCode(material_int),
                area_pixels=area_px,
                bbox_pixel=(minx, miny, maxx, maxy),
            )
        )

    records.sort(key=lambda r: r.area_pixels, reverse=True)
    return records


def iter_polygon_regions(
    rgb_image: np.ndarray,
    records: list[SanbornPolygonRecord],
) -> Iterator[tuple[SanbornPolygonRecord, np.ndarray]]:
    """Yield (record, cropped_rgb_patch) pairs for downstream OCR or
    visual inspection. The patch is the axis-aligned bbox of the
    polygon in the original RGB image — useful for Tesseract /
    VLM-based story-count extraction.
    """
    for record in records:
        minx, miny, maxx, maxy = record.bbox_pixel
        x0, y0 = max(0, int(minx)), max(0, int(miny))
        x1 = min(rgb_image.shape[1], int(maxx) + 1)
        y1 = min(rgb_image.shape[0], int(maxy) + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        yield record, rgb_image[y0:y1, x0:x1]


def extract_story_count(
    rgb_patch: np.ndarray,
    *,
    backend: str = "tesseract",
) -> int | None:
    """Best-effort story-count extraction from a polygon's RGB patch.

    Sanborn sheets print the story count as a small digit (often
    1, 1.5, 2, 2.5, 3) inside each building polygon. This function
    attempts OCR; if the OCR backend isn't installed or the result
    isn't a parseable small integer, it returns None gracefully
    rather than raising.

    `backend="tesseract"`: uses pytesseract. Requires the
    `tesseract` binary on PATH AND the `pytesseract` Python package.

    Higher-quality alternative (`backend="vlm"`): post the patch to
    a vision-language model. Not implemented in v0.1 — left as the
    follow-up path because VLM calls have latency + cost
    implications that need a batch-job design.
    """
    if backend != "tesseract":
        return None
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        # Graceful fallback — Tesseract is optional.
        return None

    try:
        image = Image.fromarray(rgb_patch)
        text = pytesseract.image_to_string(
            image,
            config="--psm 10 -c tessedit_char_whitelist=0123456789.",
        ).strip()
    except Exception:
        return None

    # Sanborn story counts are small integers (1, 2, 3) or
    # half-stories (1.5, 2.5). For the v0.1 cut we coerce halves
    # down to int. Numbers >5 are almost certainly wrong (a 6-story
    # frame house doesn't exist on Sanborn sheets); reject them.
    try:
        value = float(text)
        if 0.5 <= value <= 5.0:
            return max(1, int(value))
    except (ValueError, TypeError):
        pass
    return None
