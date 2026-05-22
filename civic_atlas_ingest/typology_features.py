"""
Phase A typology — feature extraction pipeline.

Per-building feature vector construction:
  - Geometric features from Shapely on the footprint
  - OSM-tag features (one-hot over the fixed-vocab `building` values)
  - Parcel-context features from the spatial join with the Flint
    parcel layer (zoning code as one-hot, parcel_area_m2,
    parcel_area_ratio)
  - Completeness flags so the classifier knows what it doesn't know

Determinism per spec §10 MUST: same (osm_snapshot, parcel_snapshot,
feature_version) MUST produce identical feature vectors. This is
honored by computing every feature deterministically from input
geometry + properties without random state.

Spec reference: SPEC-PHASE-A-TYPOLOGY.md §4 (Feature engineering).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry


FEATURE_VERSION = "features-v0.1.0"


# OSM building tag values worth one-hot encoding. Covers the values
# actually present in the Flint fixture (verified 2026-05-22) plus a
# few standard OSM tags that may appear in future data.
BUILDING_TAG_VOCAB: tuple[str, ...] = (
    "yes",
    "house",
    "apartments",
    "detached",
    "semidetached_house",
    "terrace",
    "residential",
    "garage",
    "shed",
    "carport",
    "commercial",
    "retail",
    "office",
    "industrial",
    "warehouse",
    "school",
    "church",
    "university",
    "hospital",
    "public",
    "civic",
    "government",
    "library",
    "museum",
    "service",
    "roof",
)


# Flint zoning code one-hot vocabulary. Verified against the parcel
# data (top codes by frequency). Codes not in this list are bucketed
# into `zoning_other`.
ZONING_VOCAB: tuple[str, ...] = (
    "TN-1",
    "TN-2",
    "GN-1",
    "GN-2",
    "MR-1",
    "MR-2",
    "MR-3",
    "GI-1",
    "GI-2",
    "CC",
    "UC",
    "NC",
    "CE",
    "DE",
    "OS",
    "PC",
    "DC",
    "IC",
)


@dataclass(frozen=True)
class FeatureColumns:
    """Names of the columns produced by `extract_features_for_joined`."""

    geometric: tuple[str, ...] = (
        "area_m2",
        "perimeter_m",
        "perimeter_area_ratio",
        "convex_hull_ratio",
        "vertex_count",
        "aspect_ratio",
        "axis_long_m",
        "axis_short_m",
        "compactness",
    )
    parcel: tuple[str, ...] = (
        "parcel_area_m2",
        "parcel_area_ratio",
        "has_parcel_join",
    )
    completeness: tuple[str, ...] = (
        "has_osm_use_tag",
        "has_height_signal",
        "feature_completeness",
    )


FEATURE_COLUMNS = FeatureColumns()


def extract_geometric_features(footprint: BaseGeometry) -> dict[str, float]:
    """
    Shapely-based geometric features on a single footprint polygon.

    Returns area_m2, perimeter_m, perimeter_area_ratio, convex_hull_ratio,
    vertex_count, aspect_ratio (long-axis / short-axis), axis_long_m,
    axis_short_m, compactness (4π·area / perimeter²).

    Aspect ratio is computed via the minimum-rotated-rectangle bounding
    box; this is robust to L-shaped footprints (the bbox aligns with the
    building's actual long axis, not the cardinal axes).
    """
    if footprint is None or footprint.is_empty:
        return {col: math.nan for col in FEATURE_COLUMNS.geometric}

    # All metric calculations want a projected CRS. The caller is
    # responsible for ensuring the geometry is in a meter-based CRS
    # (this module is called from inside the joined GeoDataFrame
    # pipeline which projects to EPSG:3857 first).
    area = footprint.area
    perimeter = footprint.length
    perimeter_area_ratio = perimeter / area if area > 0 else math.nan
    convex_hull_area = footprint.convex_hull.area
    convex_hull_ratio = area / convex_hull_area if convex_hull_area > 0 else math.nan
    vertex_count = _count_vertices(footprint)
    compactness = (
        4 * math.pi * area / (perimeter * perimeter) if perimeter > 0 else math.nan
    )

    # Minimum-rotated-rectangle for robust aspect ratio.
    mrr = footprint.minimum_rotated_rectangle
    axis_long, axis_short = _rotated_bbox_axes(mrr)
    aspect_ratio = axis_long / axis_short if axis_short > 0 else math.nan

    return {
        "area_m2": area,
        "perimeter_m": perimeter,
        "perimeter_area_ratio": perimeter_area_ratio,
        "convex_hull_ratio": convex_hull_ratio,
        "vertex_count": float(vertex_count),
        "aspect_ratio": aspect_ratio,
        "axis_long_m": axis_long,
        "axis_short_m": axis_short,
        "compactness": compactness,
    }


def _count_vertices(geometry: BaseGeometry) -> int:
    """Count exterior-ring vertices for Polygon; sum across parts for MultiPolygon."""
    if isinstance(geometry, Polygon):
        return len(geometry.exterior.coords) - 1  # closing duplicate
    if hasattr(geometry, "geoms"):
        return sum(_count_vertices(g) for g in geometry.geoms)
    return 0


def _rotated_bbox_axes(rotated_bbox: BaseGeometry) -> tuple[float, float]:
    """Return (long_axis_m, short_axis_m) from a minimum-rotated-rectangle."""
    if rotated_bbox is None or rotated_bbox.is_empty:
        return (math.nan, math.nan)
    coords = list(rotated_bbox.exterior.coords)
    if len(coords) < 5:
        return (math.nan, math.nan)
    # The MRR has 4 unique corners + closing point. Side lengths come
    # from consecutive pairs.
    side_a = math.hypot(coords[1][0] - coords[0][0], coords[1][1] - coords[0][1])
    side_b = math.hypot(coords[2][0] - coords[1][0], coords[2][1] - coords[1][1])
    return (max(side_a, side_b), min(side_a, side_b))


def building_tag_features(building_tag: Any) -> dict[str, int]:
    """One-hot the `building` tag against BUILDING_TAG_VOCAB."""
    tag = building_tag.strip().lower() if isinstance(building_tag, str) else ""
    return {
        f"building_tag__{vocab}": int(tag == vocab) for vocab in BUILDING_TAG_VOCAB
    }


def zoning_features(zoning: Any) -> dict[str, int]:
    """One-hot the parcel zoning code against ZONING_VOCAB. Falls into `zoning_other`."""
    z = zoning.strip() if isinstance(zoning, str) else ""
    one_hot = {f"zoning__{code}": int(z == code) for code in ZONING_VOCAB}
    one_hot["zoning__other"] = int(bool(z) and z not in ZONING_VOCAB)
    one_hot["zoning__missing"] = int(not z)
    return one_hot


def completeness_features(
    osm_props: dict[str, Any],
    has_parcel_join: bool,
) -> dict[str, float | int]:
    """
    Per-row completeness signals. `feature_completeness` is the
    weighted real number in [0, 1] per spec §10 MUST.
    """
    has_osm_use_tag = bool(osm_props.get("use"))
    has_height_signal = bool(
        osm_props.get("height_meters") is not None or osm_props.get("levels") is not None
    )
    # Weights chosen to put parcel-join at the dominant ~50% of
    # completeness, with use-tag and height contributing smaller deltas.
    score = 0.30
    if has_parcel_join:
        score += 0.50
    if has_osm_use_tag:
        score += 0.10
    if has_height_signal:
        score += 0.10
    return {
        "has_osm_use_tag": int(has_osm_use_tag),
        "has_height_signal": int(has_height_signal),
        "feature_completeness": min(1.0, score),
    }


def extract_features_for_joined(joined: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Vectorized feature extraction across an already-joined GeoDataFrame
    (output of typology_join.join_buildings_to_parcels).

    Returns a pandas DataFrame indexed by the same index as `joined`,
    with all feature columns from FEATURE_COLUMNS plus the one-hot
    building_tag__* and zoning__* columns.
    """
    # Reproject to EPSG:3857 once for all metric geometry calculations.
    joined_m = joined.to_crs(epsg=3857)

    rows: list[dict[str, Any]] = []
    for idx, row in joined_m.iterrows():
        geom = row.geometry
        feats = extract_geometric_features(geom)
        feats.update(building_tag_features(row.get("building")))
        feats.update(zoning_features(row.get("parcel_zoning")))
        has_join = bool(row.get("has_parcel_join", False))
        feats["parcel_area_m2"] = (
            float(row["parcel_area_m2"]) if has_join and pd.notna(row.get("parcel_area_m2")) else math.nan
        )
        feats["parcel_area_ratio"] = (
            float(row["parcel_area_ratio"])
            if has_join and pd.notna(row.get("parcel_area_ratio"))
            else math.nan
        )
        feats["has_parcel_join"] = int(has_join)
        feats.update(
            completeness_features(
                {
                    "use": row.get("use"),
                    "height_meters": row.get("height_meters"),
                    "levels": row.get("levels"),
                },
                has_parcel_join=has_join,
            )
        )
        rows.append(feats)

    return pd.DataFrame(rows, index=joined.index)
