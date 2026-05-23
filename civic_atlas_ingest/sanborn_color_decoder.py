"""Sanborn fire-insurance map color-key decoder.

Sanborn sheets use a standardized color key to encode building material:

  yellow  → wood frame (combustible)
  pink    → brick
  red     → brick (older Sanborn editions saturated pink)
  blue    → stone
  gray    → iron or steel (incombustible metal)
  brown   → adobe / mud
  olive   → special combustible material (sometimes)
  white   → background / paper / gutters
  black   → printed labels, lot lines, story-count digits

This module classifies each pixel in a Sanborn sheet into one of the
above categories via HSV thresholding. Output is a uint8 raster where
each pixel value is a member of `MaterialCode`.

Why HSV not RGB: paper aging, scanner gamma, and digitization noise
shift RGB values significantly across the LoC archive's Sanborn
collection. Hue is robust to those shifts; saturation + value
distinguish "actual building color" from "off-white paper background."

The decoder is intentionally simple (numpy + threshold tuples). The
v0.2 path is per-edition calibration — different Sanborn print runs
shift hue slightly. v0.1 ships with thresholds tuned against Library
of Congress Flint 1899 + 1925 + 1929 samples; the calibration can
move into per-sheet manifest files later.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

import numpy as np


class MaterialCode(IntEnum):
    """Per-pixel material classification. Values are stable; new
    materials append at the end so existing rasters remain readable."""

    BACKGROUND = 0
    WOOD_FRAME = 1  # yellow
    BRICK = 2  # pink / red
    STONE = 3  # blue
    IRON = 4  # gray
    ADOBE = 5  # brown
    SPECIAL_COMBUSTIBLE = 6  # olive (rare)
    LABEL = 7  # black printed text / lines / lot boundaries


# HSV thresholds. Hue is in [0, 360) (degrees), saturation and value
# are in [0, 1]. A pixel matches a band when ALL three components
# fall within the band's open intervals (h_min <= H < h_max, etc.).
#
# Tuned against Library of Congress digitized Sanborn-Flint sheets
# from 1899, 1925, 1929. Per-sheet calibration overrides can move
# into the sheet's georeferencing JSON in v0.2.
@dataclass(frozen=True)
class HsvBand:
    code: MaterialCode
    h_min: float
    h_max: float
    s_min: float
    s_max: float
    v_min: float
    v_max: float


# Order matters: bands earlier in the list win when ranges overlap
# (e.g. the LABEL band catches deep blacks before the IRON gray band
# can claim them, because tone separation in shadows is unreliable).
DEFAULT_BANDS: tuple[HsvBand, ...] = (
    # Labels and lines: very low value, any hue, any saturation.
    HsvBand(MaterialCode.LABEL, 0, 360, 0.0, 1.0, 0.0, 0.18),
    # Iron gray: low saturation + mid value range. Cooler than warm
    # paper background; comes before background test.
    HsvBand(MaterialCode.IRON, 0, 360, 0.0, 0.18, 0.30, 0.65),
    # Background paper: very low saturation, high value.
    HsvBand(MaterialCode.BACKGROUND, 0, 360, 0.0, 0.18, 0.65, 1.0),
    # Yellow wood-frame band: hue ~45-65°, well-saturated.
    HsvBand(MaterialCode.WOOD_FRAME, 38, 68, 0.35, 1.0, 0.45, 1.0),
    # Olive special-combustible: hue ~65-90°, mid-saturation.
    HsvBand(MaterialCode.SPECIAL_COMBUSTIBLE, 68, 90, 0.30, 0.75, 0.30, 0.85),
    # Pink/red brick: two hue bands flank the 0°/360° wraparound.
    # Pink: ~325-360°. Red: ~0-15°.
    HsvBand(MaterialCode.BRICK, 325, 360, 0.20, 1.0, 0.45, 1.0),
    HsvBand(MaterialCode.BRICK, 0, 15, 0.30, 1.0, 0.40, 1.0),
    # Blue stone: hue ~200-235°.
    HsvBand(MaterialCode.STONE, 195, 245, 0.25, 1.0, 0.30, 1.0),
    # Brown adobe: hue ~20-35°, mid-saturation, mid-value.
    HsvBand(MaterialCode.ADOBE, 18, 35, 0.30, 0.85, 0.25, 0.70),
)


def rgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
    """Convert an RGB image (H, W, 3) with uint8 channels to HSV (H, W, 3)
    with hue in [0, 360), saturation and value in [0, 1].

    This is the matplotlib/colorsys convention. Pure numpy so it
    works without scikit-image; vectorized so it scales to LoC-sized
    sheets (often 6000×8000 pixels per sheet).
    """
    if rgb.dtype != np.uint8:
        raise ValueError(f"expected uint8 RGB; got {rgb.dtype}")
    if rgb.ndim != 3 or rgb.shape[-1] != 3:
        raise ValueError(f"expected (H, W, 3) RGB; got shape {rgb.shape}")

    rgb_f = rgb.astype(np.float32) / 255.0
    r, g, b = rgb_f[..., 0], rgb_f[..., 1], rgb_f[..., 2]
    max_c = np.maximum(np.maximum(r, g), b)
    min_c = np.minimum(np.minimum(r, g), b)
    delta = max_c - min_c

    # Value channel.
    v = max_c

    # Saturation channel; avoid divide-by-zero on pure black.
    s = np.where(max_c > 0, delta / np.maximum(max_c, 1e-8), 0.0)

    # Hue channel.
    h = np.zeros_like(max_c)
    mask = delta > 1e-8
    r_is_max = mask & (max_c == r)
    g_is_max = mask & (max_c == g) & ~r_is_max
    b_is_max = mask & (max_c == b) & ~r_is_max & ~g_is_max
    h[r_is_max] = (60.0 * ((g[r_is_max] - b[r_is_max]) / delta[r_is_max])) % 360.0
    h[g_is_max] = 60.0 * ((b[g_is_max] - r[g_is_max]) / delta[g_is_max]) + 120.0
    h[b_is_max] = 60.0 * ((r[b_is_max] - g[b_is_max]) / delta[b_is_max]) + 240.0
    h = h % 360.0

    hsv = np.stack([h, s, v], axis=-1)
    return hsv


def classify_pixels(
    rgb: np.ndarray,
    bands: tuple[HsvBand, ...] = DEFAULT_BANDS,
) -> np.ndarray:
    """Classify each pixel of an RGB image into a MaterialCode.

    Returns a uint8 raster (H, W) where each value is a MaterialCode
    integer. Pixels that match no band fall to `BACKGROUND` (zero).

    Order-sensitive: the first matching band wins. See DEFAULT_BANDS
    comments for the deliberate ordering choices.
    """
    hsv = rgb_to_hsv(rgb)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    out = np.zeros(rgb.shape[:2], dtype=np.uint8)
    assigned = np.zeros(rgb.shape[:2], dtype=bool)

    for band in bands:
        if band.h_min <= band.h_max:
            hue_match = (h >= band.h_min) & (h < band.h_max)
        else:
            # Wraparound band, e.g. 350°-10° (not used by default but
            # supported so callers can register bands that cross 0°).
            hue_match = (h >= band.h_min) | (h < band.h_max)
        sat_match = (s >= band.s_min) & (s < band.s_max)
        val_match = (v >= band.v_min) & (v < band.v_max)
        match = hue_match & sat_match & val_match & ~assigned
        out[match] = int(band.code)
        assigned |= match

    return out


def classification_summary(classified: np.ndarray) -> dict[str, Any]:
    """Pixel-count and area-fraction summary by material.

    Useful as a sanity check after running classify_pixels: a well-
    formed Sanborn sheet should have mostly BACKGROUND + LABEL,
    with the building-material pixels concentrated in the 10-40%
    range depending on the sheet's coverage density.
    """
    total = int(classified.size)
    out: dict[str, Any] = {"total_pixels": total, "by_material": {}}
    if total == 0:
        return out

    for code in MaterialCode:
        count = int(np.sum(classified == int(code)))
        out["by_material"][code.name.lower()] = {
            "count": count,
            "fraction": round(count / total, 4),
        }
    return out
