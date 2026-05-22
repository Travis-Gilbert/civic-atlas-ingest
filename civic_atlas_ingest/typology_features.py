"""
Phase A typology — feature extraction pipeline.

Per-building feature vector construction. Combines:
  - Geometric features from Shapely on the footprint
  - OSM-tag features (one-hot or hash-bucket for open-vocab tags)
  - Spatial-context features from OSMnx (road class, distance to road,
    neighbor density) and the parcel join (zoning, parcel area ratio)
  - Completeness flags so the classifier knows what it doesn't know

Scaffolded 2026-05-22. Implementation pending A3 (hand-labeled
validation set). The features ARE definable now from the spec, but
since the classifier hasn't been trained yet, locking in a feature
spec without iteration risks shipping a sub-optimal feature set.
The function signatures are stable; the bodies await first training
run.

Spec reference: SPEC-PHASE-A-TYPOLOGY.md §4 (Feature engineering).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    import geopandas as gpd  # noqa: F401  (re-exported via type hints)
    from shapely.geometry.base import BaseGeometry  # noqa: F401
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "typology_features requires GeoPandas + Shapely. Install with "
        "`pip install -e .` (base deps) from civic-atlas-ingest root."
    ) from exc


@dataclass(frozen=True)
class FeatureSnapshotInputs:
    """
    Inputs to a deterministic feature snapshot.

    Determinism per spec §10 MUST: same (osm_snapshot, parcel_snapshot,
    feature_version) MUST produce identical features.
    """

    osm_snapshot_uri: str
    parcel_snapshot_uri: str
    road_network_uri: str
    feature_version: str
    city_pack: str


def extract_geometric_features(footprint: Any) -> dict[str, float]:
    """
    Shapely-based geometric features on a single footprint.

    Returns: area_m2, perimeter_m, perimeter_area_ratio,
    convex_hull_ratio, vertex_count, aspect_ratio, axis_long_m,
    axis_short_m, compactness.

    Open question for implementor: aspect_ratio derivation method
    (minimum-rotated-rectangle vs eigen-decomposition of vertex
    covariance). Spec §4 doesn't pin it; the choice affects which
    buildings register as "long-narrow industrial" by shape alone.
    """
    raise NotImplementedError(
        "extract_geometric_features pending A2 implementation. "
        "Decision needed: aspect_ratio via minimum-rotated-rectangle "
        "or eigen-decomposition? Note in feature_spec.yaml when chosen."
    )


def extract_osm_tag_features(properties: dict[str, Any]) -> dict[str, Any]:
    """
    OSM-tag features from a single building's properties dict.

    One-hot for fixed-vocab tags (building, amenity, shop, office,
    industrial, landuse). Hash-bucket for open-vocab name/operator
    if those are used downstream.

    Open question for implementor: hash-bucket dim (256? 1024?) and
    whether to include name at all. Spec §4 lists `has_addr_housenumber`
    as a residential signal; that's a boolean derived feature.
    """
    raise NotImplementedError(
        "extract_osm_tag_features pending A2 implementation. "
        "Decision needed: open-vocab handling (one-hot known list "
        "only, vs hash-bucket, vs drop). Document in feature_spec.yaml."
    )


def extract_spatial_context_features(
    footprint: Any,
    road_network: Any,
    parcel_data: Any,
    neighbors: Any,
) -> dict[str, float | str | None]:
    """
    Spatial-context features per spec §4.

    Returns: dist_to_nearest_road_m, road_class_nearest,
    neighbor_count_50m, neighbor_count_100m,
    dominant_zoning_in_parcel, parcel_area_ratio.

    Uses OSMnx (already in `pyproject.toml`) for road-network access.
    Parcel join needs the Flint zoning GeoJSON URL captured in
    `docs/data-sources.md` (A3-task-2 from the implementation plan).
    """
    raise NotImplementedError(
        "extract_spatial_context_features pending A3-task-2 "
        "(Flint zoning GeoJSON URL capture). See "
        "docs/plans/atlas-typology-phase-a-implementation.md in the "
        "Open-Flint-Atlas-main-release repo."
    )


def compute_completeness_flags(
    has_parcel_join: bool,
    has_osm_use_tag: bool,
    has_height_signal: bool,
) -> dict[str, bool | float]:
    """
    Boolean flags + a 0-1 feature_completeness scalar per spec §10 MUST.

    `feature_completeness` is a REAL number in [0, 1], not a boolean —
    the renderer multiplies confidence by it. The weighting between
    the three component signals is a design knob; A2 implementation
    decides the coefficients.
    """
    raise NotImplementedError(
        "compute_completeness_flags pending A2 implementation. "
        "Decision needed: weight coefficients for parcel/use/height "
        "signals. Spec §10 MUST: feature_completeness is real, not "
        "boolean."
    )


def build_feature_snapshot(inputs: FeatureSnapshotInputs) -> Any:
    """
    End-to-end feature pipeline: read OSM + parcels + road network,
    compute every per-building feature, write a deterministic snapshot
    to DuckDB.

    Returns: path to the DuckDB feature snapshot file.

    Determinism: same inputs MUST produce identical output bytes per
    spec §10. The snapshot file is content-addressed by its hash; the
    same hash means the same features for the same city pack.
    """
    raise NotImplementedError(
        "build_feature_snapshot pending A2 implementation. Composes "
        "the four extract_* helpers above plus a DuckDB writer. "
        "Determinism MUST be verified by running twice and comparing "
        "the snapshot file hash."
    )
