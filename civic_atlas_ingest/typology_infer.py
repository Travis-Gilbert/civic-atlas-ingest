"""
Phase A typology — batch inference entrypoint.

Ray batch job that loads a versioned city pack (classifier + calibrator
+ feature spec + class map + parcel zoning snapshot), runs the feature
extraction pipeline over every building in a city's OSM extract, and
writes one row per (osm_id, model_version, city_pack) to the
`building_typology` PostGIS table.

Scaffolded 2026-05-22. Implementation pending A4 (training).

Spec reference: SPEC-PHASE-A-TYPOLOGY.md §6 (city pack structure), §7
(PostGIS), §10 (idempotency, model_version stamping).

Runtime: Ray on RunPod. Idempotent per spec §10 MUST: same inputs +
same model_version produce identical output rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from civic_atlas_ingest.typology_schema import TypologyConfig, TypologyRow


@dataclass(frozen=True)
class InferenceJobInputs:
    """Versioned inputs for an idempotent batch inference run."""

    config: TypologyConfig
    city_pack_root: Path
    osm_extract_uri: str
    feature_snapshot_uri: str
    output_postgis_dsn: str


def run_batch_inference(inputs: InferenceJobInputs) -> int:
    """
    Run a deterministic batch inference pass over every building in
    the OSM extract, writing rows to PostGIS.

    Pipeline:
      1. Load classifier + calibrator + feature spec + class map from
         city pack at `inputs.city_pack_root / typology /`.
      2. Verify the loaded artifacts' model_version matches
         `inputs.config.model_version`.
      3. Read feature snapshot via DuckDB (already computed by
         `typology_features.build_feature_snapshot`).
      4. For each row: raw LightGBM probabilities -> isotonic
         calibration -> per_class_proba dict -> argmax + threshold
         check -> TypologyClass (UNKNOWN if max-proba below
         `config.confidence_threshold`).
      5. Validate each TypologyRow via Pydantic.
      6. Bulk insert into building_typology with ON CONFLICT DO
         UPDATE (idempotent for the same model_version + city_pack).

    Returns: row count written.

    Per spec §10 MUST: same (OSM snapshot, parcel snapshot,
    model_version, feature_version) produce identical output rows.
    Verified by running the job twice and asserting equal output
    hashes.
    """
    raise NotImplementedError(
        "run_batch_inference pending A4 (training) completion. The "
        "Ray cluster setup is in place; the entrypoint script is "
        "ready; what's missing is the trained model to load."
    )


def predict_single_row(
    feature_vector: dict[str, Any],
    classifier: Any,
    calibrator: Any,
    config: TypologyConfig,
) -> TypologyRow:
    """
    Predict one row, public for testability.

    Used by the per-row mapper in `run_batch_inference` and exposed
    here so unit tests can drive predictions without touching Ray.
    """
    raise NotImplementedError(
        "predict_single_row pending A4 completion. The calibration "
        "+ argmax + threshold pipeline is straightforward once a "
        "classifier exists to drive it."
    )
