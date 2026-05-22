"""
Phase A typology — labeled validation set loader.

The 200-building hand-labeled validation set is HUMAN-required input
(A3-task-1 from the implementation plan). This module loads it from
the city pack and provides active-learning hooks for future
iterations.

Per spec §10 MUST: "Validation set is held back from training, never
leaked." This module enforces that by exposing the validation set as
a separate function from any training-data getter, with assertions
that prevent accidental mixing.

Scaffolded 2026-05-22. Implementation pending A3-task-1.

Spec reference: SPEC-PHASE-A-TYPOLOGY.md §10 (Validation set MUSTs)
and §11 (Done definition: macro f1 >= 0.75).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import geopandas as gpd  # noqa: F401
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "typology_labels requires GeoPandas. Install with "
        "`pip install -e .` from civic-atlas-ingest root."
    ) from exc


VALIDATION_SET_REL_PATH = "typology/validation_set.geojson"


def load_validation_set(city_pack_root: Path) -> Any:
    """
    Load the hand-labeled validation set for a city pack.

    Path: `{city_pack_root}/typology/validation_set.geojson`

    Schema per row:
      - osm_id (int)
      - typology_class (str, one of TypologyClass values)
      - typology_confidence_human (float in [0, 1]; labeler's
        confidence in their own label)
      - labeled_at (ISO8601 timestamp)
      - labeler_id (string, who labeled this row)
      - ward_number (int 1-9 for stratification verification)

    Returns: a GeoDataFrame.

    Raises: FileNotFoundError if the validation set has not been
    created yet. That file is HUMAN-required input — there is no
    automated path to it.
    """
    path = city_pack_root / VALIDATION_SET_REL_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Validation set not found at {path}. This is a "
            "human-required artifact (A3-task-1 from the Phase A "
            "implementation plan). Use QGIS or a labeling tool to "
            "hand-label 200+ Flint buildings stratified across all "
            "9 wards before training. Spec §10 MUST: 'Validation set "
            "is held back from training, never leaked.'"
        )
    raise NotImplementedError(
        "load_validation_set body pending A3-task-1 completion. "
        "When the file exists, this function reads it with "
        "geopandas.read_file and validates the per-row schema."
    )


def stratification_report(validation_set: Any) -> dict[str, Any]:
    """
    Verify the validation set is stratified per spec requirements:
      - 200+ buildings minimum
      - At least 15 per ward (covers all 9 wards)
      - All 6 typology classes present
      - No osm_id appears more than once
    """
    raise NotImplementedError(
        "stratification_report pending A3-task-1. Reads the loaded "
        "validation set and produces a sanity check dict before any "
        "training run consumes it."
    )


def active_learning_candidates(
    feature_snapshot: Any,
    classifier_predictions: Any,
    confidence_threshold: float = 0.5,
    n: int = 50,
) -> Any:
    """
    Return the top-N highest-uncertainty buildings as candidates for
    human re-labeling, for the next training iteration.

    Uncertainty signal: entropy of `per_class_proba`. Highest-entropy
    rows are the ones the classifier is least sure about; labeling
    those gives the most information per label.

    Stretch goal per spec §4 mention of active learning. Initial
    Phase A release ships without it; this signature reserves the
    surface so the v0.2 retrain can read this without API churn.
    """
    raise NotImplementedError(
        "active_learning_candidates is a v0.2 stretch goal. Initial "
        "Phase A ships with passive labeled-set training only."
    )
