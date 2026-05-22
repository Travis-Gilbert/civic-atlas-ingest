"""
Phase A typology — training entrypoint.

LightGBM classifier trained on Ray. Hyperparameter tuning via Ray Tune.
Isotonic calibration of output probabilities via scikit-learn (separate
pipeline stage per spec §10 MUST).

Scaffolded 2026-05-22. Implementation pending A3-task-1 (hand-labeled
validation set). The training entrypoint signature is stable; the body
awaits real labeled data.

Spec reference: SPEC-PHASE-A-TYPOLOGY.md §1 (LightGBM choice over
neural net), §5 (module layout), §10 (calibration as separate stage,
deterministic given snapshots, model_version stamping).

Runtime: Ray on RunPod per the implementation plan (replaces Modal
from the original spec).

Serialization note: classifier persists via LightGBM's native binary
format (.lgb). Calibrator persists via joblib (sklearn's recommended
serializer; same security profile as pickle, but never loaded from
untrusted sources — only from artifacts the inference job wrote
itself into the city pack).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from civic_atlas_ingest.typology_schema import TypologyConfig


@dataclass(frozen=True)
class TrainingArtifacts:
    """Outputs of a successful training run, all content-addressed."""

    classifier_lgb_path: Path
    calibrator_joblib_path: Path
    feature_spec_yaml_path: Path
    class_map_yaml_path: Path
    metadata_json_path: Path
    metrics: dict[str, float]  # macro_f1, per_class_f1, calibration_ece, etc.


def train_typology_classifier(
    config: TypologyConfig,
    feature_snapshot_uri: str,
    validation_set_path: Path,
    city_pack_root: Path,
    output_root: Path,
    ray_tune_num_samples: int = 50,
) -> TrainingArtifacts:
    """
    Train the LightGBM typology classifier with Ray Tune hyperparameter
    search.

    Pipeline:
      1. Load feature snapshot via DuckDB.
      2. Load + verify validation set via typology_labels.
      3. Hold validation set out completely (spec §10 MUST).
      4. Ray Tune sweep over LightGBM hyperparameters (num_leaves,
         learning_rate, min_data_in_leaf, lambda_l1, lambda_l2,
         feature_fraction, bagging_fraction).
      5. Best model selected by macro F1 on a held-out training-set
         split (NOT the validation set — that's still held back).
      6. Isotonic calibration of best model's probabilities on the
         training-set holdout slice.
      7. Final evaluation on the validation set produces per-class
         f1, macro f1, confusion matrix, reliability diagram.
      8. Writes city pack artifacts to `output_root/typology/`.
      9. Stamps every artifact with `config.model_version`.

    Spec MUSTs honored:
      - Determinism: same snapshots + same config -> same artifacts.
        Verified by hashing the output artifacts.
      - Calibration is a separate stage; raw LightGBM probabilities
        are not used as confidence directly.
      - model_version stamped in every artifact's metadata.
      - Validation set never leaked into training.

    Done-criterion check: macro f1 >= 0.75 on validation set per
    spec §A4. Implementation should raise (not silently warn) if the
    metric falls below threshold.

    Returns: TrainingArtifacts with paths + metrics. Caller is
    responsible for committing the artifacts to the city pack and
    bumping the active-model pointer.
    """
    raise NotImplementedError(
        "train_typology_classifier pending A3-task-1 completion. "
        "Cannot meaningfully train without a hand-labeled validation "
        "set. See docs/plans/atlas-typology-phase-a-implementation.md "
        "(Open-Flint-Atlas-main-release repo) for the human-required "
        "labeling tasks that unblock this."
    )


def calibrate_probabilities(
    raw_proba: Any,
    calibration_set_labels: Any,
) -> Any:
    """
    Isotonic regression on validation-set-adjacent calibration holdout.

    Spec §10 MUST: "Confidence calibration runs as a separate pipeline
    stage; raw LightGBM probabilities are NOT used as confidence
    directly." This function is that separate stage.

    Output: a scikit-learn IsotonicRegression model serialized to
    disk via joblib for the inference pipeline to load alongside the
    LightGBM model.
    """
    raise NotImplementedError(
        "calibrate_probabilities pending A4 completion. Standard "
        "scikit-learn isotonic regression once raw probabilities + "
        "labels are available from the trained model."
    )


def write_city_pack_metadata(
    config: TypologyConfig,
    artifacts: TrainingArtifacts,
    output_root: Path,
) -> Path:
    """
    Write `metadata.json` to the city pack with:
      - training run timestamp + git SHA
      - dataset hashes (feature snapshot, parcel snapshot, OSM snapshot)
      - validation metrics
      - model_version + feature_version pointers
      - config snapshot

    Inference job loads by version, never by 'latest' pointer per spec
    §A4 metadata.json bullet.
    """
    raise NotImplementedError(
        "write_city_pack_metadata pending A4 completion. Trivial "
        "JSON dump once TrainingArtifacts is real."
    )
