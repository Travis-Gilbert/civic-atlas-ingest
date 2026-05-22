"""
Phase A typology — evaluation utilities.

Confusion matrix, per-class precision/recall/F1, calibration
reliability diagram, per-ward stratification check.

Scaffolded 2026-05-22. Implementation pending A4 (training).

Spec reference: SPEC-PHASE-A-TYPOLOGY.md §A4 (macro f1 >= 0.75),
§A5 (calibration reliability diagram bins within 5% of diagonal),
§11 (Done definition).
"""

from __future__ import annotations

from typing import Any


def compute_confusion_matrix(
    y_true: Any,
    y_pred: Any,
) -> Any:
    """Standard confusion matrix over the 6 TypologyClass values."""
    raise NotImplementedError(
        "compute_confusion_matrix pending A4. Use sklearn.metrics."
    )


def per_class_metrics(y_true: Any, y_pred: Any) -> dict[str, dict[str, float]]:
    """Per-class precision, recall, F1; plus macro F1."""
    raise NotImplementedError(
        "per_class_metrics pending A4. Use sklearn.metrics.classification_report."
    )


def calibration_reliability_diagram(
    y_true: Any,
    y_proba: Any,
    n_bins: int = 10,
) -> dict[str, Any]:
    """
    Reliability diagram for the calibrated probabilities.

    Spec §A5: "reliability diagram bins within 5% of diagonal."
    Computes per-bin observed-frequency vs predicted-confidence and
    returns the points plus an `ece` (Expected Calibration Error)
    scalar for pass/fail.
    """
    raise NotImplementedError(
        "calibration_reliability_diagram pending A4 + A5. Plot via "
        "matplotlib in a separate notebook; this function returns "
        "the data structure ready to plot."
    )


def per_ward_stratification_check(
    validation_set: Any,
    predictions: Any,
) -> dict[str, Any]:
    """
    Sanity check: how well does the model perform across the 9 Flint
    wards? Imbalanced per-ward performance is a signal that the model
    has learned the bias of the labelers' availability bias rather
    than the underlying typology.
    """
    raise NotImplementedError(
        "per_ward_stratification_check pending A4 + A3-task-1. "
        "Per-ward f1 should be within 0.1 of macro f1 across wards "
        "for the result to be trustworthy as a citywide classifier."
    )
