"""
End-to-end Phase A typology pipeline for Flint.

Pipeline:
  1. Load Flint parcels (cache/flint_parcels.geojson)
  2. Load Open-Flint-Atlas OSM building fixture
  3. Spatial-join buildings to parcels (centroid-in-parcel)
  4. Derive labels (parcel Use_Type + OSM-tag civic override)
  5. Extract features (geometric + tag + parcel context)
  6. Train LightGBM on known-label rows with stratified 80/20 split
  7. Isotonic calibration of probabilities on held-out fold
  8. Inference over ALL buildings (including unknowns the classifier
     has to guess about)
  9. Write city pack artifacts:
       packs/us/mi/flint/typology/classifier.lgb
       packs/us/mi/flint/typology/calibrator.joblib
       packs/us/mi/flint/typology/metadata.json
       packs/us/mi/flint/typology/feature_spec.yaml
       packs/us/mi/flint/typology/class_map.yaml
 10. Enrich the OSM fixture with typology_class + typology_confidence
     and write back to the Open-Flint-Atlas repo so the frontend hooks
     consume real data.

Usage:
    .venv/bin/python -m scripts.build_flint_typology

Spec reference: SPEC-PHASE-A-TYPOLOGY.md (full pipeline).
"""

from __future__ import annotations

import hashlib
import json
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split

from civic_atlas_ingest.typology_features import (
    BUILDING_TAG_VOCAB,
    FEATURE_VERSION,
    ZONING_VOCAB,
    extract_features_for_joined,
)
from civic_atlas_ingest.typology_join import (
    join_buildings_to_parcels,
    load_osm_buildings,
    load_parcels,
)
from civic_atlas_ingest.typology_label_derive import derive_labels_for_joined
from civic_atlas_ingest.typology_schema import TypologyClass


# Paths
REPO_ROOT = Path(__file__).resolve().parent.parent
PARCELS_PATH = REPO_ROOT / "cache" / "flint_parcels.geojson"
CITY_PACK_DIR = REPO_ROOT / "city_packs" / "us" / "mi" / "flint" / "typology"

OPEN_FLINT_ATLAS_ROOT = Path(
    "/Users/travisgilbert/Tech Dev Local/Creative/Website/Open-Flint-Atlas-main-release"
)
OSM_FIXTURE_PATH = (
    OPEN_FLINT_ATLAS_ROOT
    / "src"
    / "data"
    / "open-flint-atlas"
    / "fixtures"
    / "osm-buildings.json"
)


# Configuration
MODEL_VERSION = "typology-v0.1.0-parcel-joined"
CITY_PACK_NAME = "us/mi/flint"
RANDOM_STATE = 42
CONFIDENCE_THRESHOLD = 0.5  # below this, force to UNKNOWN
TEST_FRAC = 0.20


def main() -> int:
    t0 = time.time()
    print("=" * 60)
    print(f"Phase A typology pipeline — {MODEL_VERSION}")
    print(f"City pack: {CITY_PACK_NAME}")
    print(f"Feature version: {FEATURE_VERSION}")
    print("=" * 60)

    CITY_PACK_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load + join + label
    print("\n[1/8] Loading parcels...")
    parcels = load_parcels(PARCELS_PATH)
    print(f"  {len(parcels)} parcels loaded.")
    parcels_hash = _hash_file(PARCELS_PATH)
    print(f"  parcels sha256: {parcels_hash[:16]}...")

    print("\n[2/8] Loading OSM buildings...")
    buildings = load_osm_buildings(OSM_FIXTURE_PATH)
    print(f"  {len(buildings)} buildings loaded.")
    buildings_hash = _hash_file(OSM_FIXTURE_PATH)
    print(f"  buildings sha256: {buildings_hash[:16]}...")

    print("\n[3/8] Spatial-joining buildings to parcels...")
    joined = join_buildings_to_parcels(buildings, parcels)
    match_rate = float(joined["has_parcel_join"].mean())
    print(f"  Join complete. Match rate: {match_rate:.1%}")

    print("\n[4/8] Deriving labels...")
    labels = derive_labels_for_joined(joined)
    label_strs = np.array([l.value for l in labels])
    label_dist = pd.Series(label_strs).value_counts().to_dict()
    for cls, count in sorted(label_dist.items(), key=lambda x: -x[1]):
        print(f"  {cls:>12}  {count:>5}  ({100 * count / len(labels):>4.1f}%)")

    # 5. Features
    print("\n[5/8] Extracting features...")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="shapely")
        features = extract_features_for_joined(joined)
    # Replace NaN/Inf in geometric features with sensible fallbacks so
    # LightGBM doesn't have to handle them inconsistently across splits.
    features = features.replace([np.inf, -np.inf], np.nan)
    geometric_cols = [
        "area_m2",
        "perimeter_m",
        "perimeter_area_ratio",
        "convex_hull_ratio",
        "vertex_count",
        "aspect_ratio",
        "axis_long_m",
        "axis_short_m",
        "compactness",
    ]
    for col in geometric_cols:
        median = features[col].median()
        features[col] = features[col].fillna(median)
    features["parcel_area_m2"] = features["parcel_area_m2"].fillna(0.0)
    features["parcel_area_ratio"] = features["parcel_area_ratio"].fillna(0.0)
    print(f"  Feature matrix: {features.shape}")

    # 6. Train (known-label rows only)
    print("\n[6/8] Training LightGBM...")
    known_mask = label_strs != "unknown"
    X_known = features.loc[known_mask].reset_index(drop=True)
    y_known = label_strs[known_mask]
    print(f"  Training pool: {len(X_known)} known-label rows.")

    # Plain Python str for serialization compatibility (numpy strings
    # break yaml.safe_dump and serialize awkwardly into JSON).
    classes = sorted({str(c) for c in y_known})
    class_to_idx = {c: i for i, c in enumerate(classes)}
    idx_to_class = {i: c for c, i in class_to_idx.items()}
    y_known_idx = np.array([class_to_idx[c] for c in y_known])

    X_train, X_test, y_train_idx, y_test_idx = train_test_split(
        X_known,
        y_known_idx,
        test_size=TEST_FRAC,
        stratify=y_known_idx,
        random_state=RANDOM_STATE,
    )
    print(f"  Split: {len(X_train)} train / {len(X_test)} test.")

    # Further split train -> sub-train + calibration holdout (10% of total)
    X_subtrain, X_cal, y_subtrain_idx, y_cal_idx = train_test_split(
        X_train,
        y_train_idx,
        test_size=0.125,  # 12.5% of 80% = 10% of total
        stratify=y_train_idx,
        random_state=RANDOM_STATE,
    )
    print(
        f"  Calibration split: {len(X_subtrain)} sub-train / "
        f"{len(X_cal)} calibration."
    )

    model = lgb.LGBMClassifier(
        n_estimators=300,
        num_leaves=31,
        learning_rate=0.05,
        objective="multiclass",
        num_class=len(classes),
        random_state=RANDOM_STATE,
        verbose=-1,
    )
    t_train = time.time()
    model.fit(X_subtrain, y_subtrain_idx)
    print(f"  Trained in {time.time() - t_train:.1f}s.")

    # 7. Calibration (per-class isotonic regression on the holdout)
    print("\n[7/8] Calibrating probabilities (isotonic per class)...")
    cal_proba = model.predict_proba(X_cal)
    calibrators: dict[int, IsotonicRegression] = {}
    for class_idx in range(len(classes)):
        is_class = (y_cal_idx == class_idx).astype(int)
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso.fit(cal_proba[:, class_idx], is_class)
        calibrators[class_idx] = iso
    print(f"  Trained {len(calibrators)} per-class calibrators.")

    # Evaluate on the held-out test set, calibrated.
    test_proba_raw = model.predict_proba(X_test)
    test_proba_cal = _apply_calibrators(test_proba_raw, calibrators)
    test_pred_idx = np.argmax(test_proba_cal, axis=1)
    test_pred = np.array([idx_to_class[int(i)] for i in test_pred_idx])
    test_true = np.array([idx_to_class[int(i)] for i in y_test_idx])
    macro_f1 = float(f1_score(test_true, test_pred, average="macro"))
    report_text = classification_report(test_true, test_pred, digits=3)
    print("\nCalibrated test set metrics:")
    print(report_text)
    print(f"Macro F1: {macro_f1:.3f} (spec §A4 floor: 0.75)")
    if macro_f1 < 0.75:
        raise RuntimeError(
            f"Macro F1 {macro_f1:.3f} below spec §A4 floor of 0.75. "
            f"Investigate before committing artifacts."
        )

    # Confusion matrix
    cm = confusion_matrix(test_true, test_pred, labels=classes)

    # 8. Inference over ALL buildings (including unknowns), enrich fixture
    print("\n[8/8] Running inference over all buildings + enriching fixture...")
    full_proba_raw = model.predict_proba(features)
    full_proba_cal = _apply_calibrators(full_proba_raw, calibrators)
    full_max_proba = full_proba_cal.max(axis=1)
    full_pred_idx = full_proba_cal.argmax(axis=1)
    # Below threshold → UNKNOWN
    below_threshold = full_max_proba < CONFIDENCE_THRESHOLD
    full_class = np.array(
        [
            idx_to_class[int(i)] if not below else "unknown"
            for i, below in zip(full_pred_idx, below_threshold, strict=True)
        ]
    )

    # Write city pack artifacts
    classifier_path = CITY_PACK_DIR / "classifier.lgb"
    model.booster_.save_model(str(classifier_path))
    print(f"  Wrote {classifier_path}")

    calibrator_path = CITY_PACK_DIR / "calibrator.joblib"
    joblib.dump({"classes": classes, "calibrators": calibrators}, calibrator_path)
    print(f"  Wrote {calibrator_path}")

    feature_spec = {
        "feature_version": FEATURE_VERSION,
        "building_tag_vocab": list(BUILDING_TAG_VOCAB),
        "zoning_vocab": list(ZONING_VOCAB),
        "geometric_features": geometric_cols,
        "parcel_features": ["parcel_area_m2", "parcel_area_ratio", "has_parcel_join"],
        "completeness_features": [
            "has_osm_use_tag",
            "has_height_signal",
            "feature_completeness",
        ],
        "feature_columns": list(features.columns),
    }
    (CITY_PACK_DIR / "feature_spec.yaml").write_text(
        yaml.safe_dump(feature_spec, sort_keys=False)
    )
    print(f"  Wrote {CITY_PACK_DIR / 'feature_spec.yaml'}")

    class_map = {
        "classes": [c.value for c in TypologyClass],
        "predicted_classes": list(classes),
        "deferred_classes": ["mixed_use"],
        "render_colors": {
            "residential": "#c19a6b",
            "commercial": "#4a8a82",
            "industrial": "#6b5d54",
            "civic": "#722f37",
            "mixed_use": "#b8893f",
            "unknown": "#a89c84",
        },
    }
    (CITY_PACK_DIR / "class_map.yaml").write_text(
        yaml.safe_dump(class_map, sort_keys=False)
    )
    print(f"  Wrote {CITY_PACK_DIR / 'class_map.yaml'}")

    metadata = {
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "city_pack": CITY_PACK_NAME,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "label_source": (
            "Flint Assessor parcel layer (gis.cityofflint.com Parcels FeatureService) "
            "joined to OSM building footprints by centroid-in-parcel, with OSM-tag-derived "
            "CIVIC overrides. NO hand-labeled validation set per spec §A3 yet — when one "
            "arrives, retrain to v0.2.0 and report f1 against that gold standard."
        ),
        "dataset_hashes": {
            "parcels_geojson": parcels_hash,
            "osm_buildings_fixture": buildings_hash,
        },
        "training": {
            "n_train": int(len(X_subtrain)),
            "n_calibration": int(len(X_cal)),
            "n_test": int(len(X_test)),
            "n_inference": int(len(features)),
            "classes_predicted": classes,
            "classes_deferred": ["mixed_use"],
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "random_state": RANDOM_STATE,
        },
        "metrics": {
            "macro_f1": macro_f1,
            "spec_floor_passed": macro_f1 >= 0.75,
            "classification_report": report_text,
            "confusion_matrix": {
                "labels": classes,
                "matrix": cm.tolist(),
            },
        },
        "limitations": {
            "no_hand_labeled_validation": (
                "Test set is a held-out 20% of the parcel-joined weak labels. "
                "Real validation against hand-labeled 200-building gold "
                "standard pending spec §A3 task. Numbers may overestimate "
                "true accuracy on buildings the parcel layer doesn't cover."
            ),
            "mixed_use_not_predicted": (
                "Mixed-use class is defined in the TypologyClass enum but not "
                "predicted in this model — current Flint parcel data has no "
                "clean mixed-use signal. v0.2.0 may add it once a better "
                "signal source exists."
            ),
            "parcel_match_rate": match_rate,
            "civic_signal_source": (
                "OSM building tag + name regex (see typology_label_derive.py). "
                "Civic buildings are typically tax-exempt and absent from the "
                "public assessor parcel layer, so the OSM-tag signal is the "
                "primary label source for this class."
            ),
        },
    }
    (CITY_PACK_DIR / "metadata.json").write_text(json.dumps(metadata, indent=2))
    print(f"  Wrote {CITY_PACK_DIR / 'metadata.json'}")

    # Enrich the OSM fixture
    print("\n[enrichment] Writing typology fields back to OSM fixture...")
    osm_data = json.loads(OSM_FIXTURE_PATH.read_text())
    for idx, feature in enumerate(osm_data["features"]):
        feature["properties"]["typology_class"] = str(full_class[idx])
        feature["properties"]["typology_confidence"] = float(
            round(full_max_proba[idx], 4)
        )
    OSM_FIXTURE_PATH.write_text(json.dumps(osm_data))
    print(f"  Enriched fixture: {OSM_FIXTURE_PATH}")
    print(
        f"  Distribution: "
        + ", ".join(
            f"{cls}={count}"
            for cls, count in sorted(
                pd.Series(full_class).value_counts().to_dict().items(),
                key=lambda x: -x[1],
            )
        )
    )
    print(f"  Mean confidence: {full_max_proba.mean():.3f}")

    print(f"\n{'=' * 60}")
    print(f"Pipeline complete in {time.time() - t0:.1f}s")
    print(f"Macro F1: {macro_f1:.3f}")
    print(f"City pack: {CITY_PACK_DIR}")
    print(f"{'=' * 60}")
    return 0


def _apply_calibrators(
    proba_raw: np.ndarray,
    calibrators: dict[int, IsotonicRegression],
) -> np.ndarray:
    """Apply per-class isotonic calibration; row-normalize to sum to 1."""
    proba_cal = np.zeros_like(proba_raw)
    for class_idx, iso in calibrators.items():
        proba_cal[:, class_idx] = iso.predict(proba_raw[:, class_idx])
    # Normalize row-wise so probabilities still sum to 1.
    row_sums = proba_cal.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    return proba_cal / row_sums


def _hash_file(path: Path) -> str:
    """SHA-256 of a file for the metadata's dataset_hashes block."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
