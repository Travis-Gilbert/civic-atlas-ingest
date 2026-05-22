"""
Phase A typology classifier — schemas and taxonomy.

This module defines the data contract for the typology classifier:
the 6-class taxonomy, the per-row Pydantic models, the pandera DataFrame
schema for the feature snapshot, and the configuration model.

Scaffolded 2026-05-22 alongside the frontend cleanup that wired the
typology consumption hooks. Implementation pending hand-labeled validation
set (see docs/plans/atlas-typology-phase-a-implementation.md
"Human-required tasks" in the Open-Flint-Atlas-main-release repo).

Spec reference: SPEC-PHASE-A-TYPOLOGY.md §2 (Class taxonomy) and §10 (MUST
clauses around determinism, confidence calibration, model_version
stamping).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Phase A typology requires Pydantic v2. Install with "
        "`pip install -e .[typology]` from civic-atlas-ingest root."
    ) from exc


class TypologyClass(str, Enum):
    """
    The Phase A taxonomy. Six classes per spec §2.

    `unknown` is the honest fallback when:
      - per-class confidence is below `TypologyConfig.confidence_threshold`, OR
      - feature completeness is below the renderer's threshold, OR
      - no real signal (tag, name, zoning, parcel) is available for the
        footprint at all.

    Mirrors the frontend's "unknown" enum member added in
    `src/lib/atlas/urban-design-model.ts` during the 2026-05-22 cleanup
    session. The frontend's `UrbanDesignFormType` is a separate taxonomy
    (geometric/spatial form, 10 members); this enum is the classifier's
    use-type taxonomy.
    """

    RESIDENTIAL = "residential"
    COMMERCIAL = "commercial"
    INDUSTRIAL = "industrial"
    CIVIC = "civic"
    MIXED_USE = "mixed_use"
    UNKNOWN = "unknown"


class TypologyConfig(BaseModel):
    """Run-time configuration for the typology classifier."""

    model_config = ConfigDict(extra="forbid")

    city_pack: str = Field(..., description="e.g. 'us/mi/flint'")
    confidence_threshold: float = Field(
        0.6,
        ge=0.0,
        le=1.0,
        description=(
            "If calibrated max-proba is below this threshold, the row "
            "is bucketed into TypologyClass.UNKNOWN regardless of "
            "argmax. Matches the frontend's "
            "applyFabricCompletenessAlpha 0.5 threshold conceptually "
            "but is enforced backend-side."
        ),
    )
    classes: list[TypologyClass] = Field(
        default_factory=lambda: list(TypologyClass),
        description="All classes the model can emit.",
    )
    feature_version: str = Field(
        ...,
        description=(
            "Pinned feature-spec version. Bump when any of the "
            "geometric / OSM-tag / spatial-context features change."
        ),
    )
    model_version: str = Field(
        ...,
        description=(
            "Per-retrain version stamp. The PostGIS primary key "
            "includes this so multiple model versions can coexist."
        ),
    )


class TypologyRow(BaseModel):
    """
    One row of the `building_typology` PostGIS table.

    This is the contract between the inference pipeline (writer) and the
    backend GraphQL resolver (reader). Same shape as the frontend's
    `OsmBuildingProperties.typology_class` + `typology_confidence` plus
    the full per-class softmax distribution.
    """

    model_config = ConfigDict(extra="forbid")

    osm_id: int
    typology_class: TypologyClass
    confidence: float = Field(..., ge=0.0, le=1.0)
    per_class_proba: dict[TypologyClass, float] = Field(
        ...,
        description=(
            "Full softmax distribution post-calibration. Keys are every "
            "non-UNKNOWN class; UNKNOWN is derived from sub-threshold "
            "max-proba, not predicted directly by the classifier."
        ),
    )
    feature_completeness: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Real number in [0, 1] per spec §10 MUST. Weighted by "
            "which signals were actually available (zoning, parcel, "
            "OSM use tag, height, neighbor density)."
        ),
    )
    model_version: str
    features_hash: str = Field(
        ...,
        description=(
            "Content hash of the feature vector that produced this "
            "prediction. Used to detect when the same building has "
            "been re-classified against a different feature snapshot."
        ),
    )
    city_pack: str


def feature_dataframe_schema() -> Any:
    """
    Return the pandera schema for the feature DataFrame.

    Columns enforced:
      - geometric: area_m2, perimeter_m, perimeter_area_ratio,
        convex_hull_ratio, vertex_count, aspect_ratio, axis_long_m,
        axis_short_m, compactness
      - OSM tags: building, building_use, amenity, shop, office,
        industrial, landuse, has_addr_housenumber, levels, height
      - spatial context: dist_to_nearest_road_m, road_class_nearest,
        neighbor_count_50m, neighbor_count_100m,
        dominant_zoning_in_parcel, parcel_area_ratio
      - completeness flags: has_parcel_join, has_osm_use_tag,
        has_height_signal

    Implementation NOT YET WRITTEN. Pandera schema construction is
    straightforward given the spec's feature list (§4), but the actual
    column dtypes depend on choices the implementor makes during A2
    (e.g. one-hot vs hash-bucket for open-vocab OSM tags). Implementing
    against an unrealized A2 would lock those choices prematurely.
    """
    raise NotImplementedError(
        "feature_dataframe_schema() requires A2 (typology_features.py) "
        "to settle the categorical encoding strategy. See "
        "civic_atlas_ingest/typology_features.py for the open decisions."
    )
