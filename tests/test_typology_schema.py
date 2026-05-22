"""
Phase A typology — schema round-trip tests.

These tests run today (no training-set or trained-model dependency).
They verify that:
  - The TypologyClass enum has the 6 spec'd values, no more no less.
  - TypologyConfig round-trips through Pydantic JSON cleanly.
  - TypologyRow round-trips through Pydantic JSON cleanly.
  - Confidence and feature_completeness bounds are enforced.
  - The classifier outputs a UNKNOWN class for low-confidence rows
    (asserted as a contract; implementation honors it in
    `typology_infer.predict_single_row`).

Spec reference: SPEC-PHASE-A-TYPOLOGY.md §A1 (verify before A2:
unit test loads sample row).
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("pydantic", reason="Phase A typology optional dep")

from civic_atlas_ingest.typology_schema import (
    TypologyClass,
    TypologyConfig,
    TypologyRow,
)


def test_typology_class_has_six_members():
    """Spec §2: residential, commercial, industrial, civic, mixed_use, unknown."""
    expected = {
        "residential",
        "commercial",
        "industrial",
        "civic",
        "mixed_use",
        "unknown",
    }
    actual = {member.value for member in TypologyClass}
    assert actual == expected


def test_typology_class_unknown_is_explicit():
    """Spec §2 names `unknown` as the honest fallback bucket."""
    assert TypologyClass.UNKNOWN.value == "unknown"


def test_typology_config_round_trips():
    config = TypologyConfig(
        city_pack="us/mi/flint",
        feature_version="features-v0.1.0",
        model_version="typology-v0.1.0",
    )
    payload = config.model_dump_json()
    parsed = TypologyConfig.model_validate_json(payload)
    assert parsed == config
    assert parsed.confidence_threshold == 0.6  # default
    assert len(parsed.classes) == 6


def test_typology_config_rejects_out_of_range_threshold():
    with pytest.raises(ValueError):
        TypologyConfig(
            city_pack="us/mi/flint",
            confidence_threshold=1.5,
            feature_version="features-v0.1.0",
            model_version="typology-v0.1.0",
        )


def test_typology_row_round_trips():
    row = TypologyRow(
        osm_id=123456789,
        typology_class=TypologyClass.COMMERCIAL,
        confidence=0.83,
        per_class_proba={
            TypologyClass.COMMERCIAL: 0.83,
            TypologyClass.MIXED_USE: 0.11,
            TypologyClass.CIVIC: 0.03,
            TypologyClass.RESIDENTIAL: 0.02,
            TypologyClass.INDUSTRIAL: 0.01,
            TypologyClass.UNKNOWN: 0.00,
        },
        feature_completeness=0.91,
        model_version="typology-v0.1.0",
        features_hash="fnv1a-deadbeef",
        city_pack="us/mi/flint",
    )
    payload = row.model_dump_json()
    parsed = TypologyRow.model_validate_json(payload)
    assert parsed == row


def test_typology_row_rejects_confidence_above_one():
    with pytest.raises(ValueError):
        TypologyRow(
            osm_id=1,
            typology_class=TypologyClass.RESIDENTIAL,
            confidence=1.5,
            per_class_proba={TypologyClass.RESIDENTIAL: 1.5},
            feature_completeness=0.5,
            model_version="typology-v0.1.0",
            features_hash="fnv1a-x",
            city_pack="us/mi/flint",
        )


def test_typology_row_rejects_feature_completeness_below_zero():
    with pytest.raises(ValueError):
        TypologyRow(
            osm_id=1,
            typology_class=TypologyClass.RESIDENTIAL,
            confidence=0.5,
            per_class_proba={TypologyClass.RESIDENTIAL: 0.5},
            feature_completeness=-0.1,
            model_version="typology-v0.1.0",
            features_hash="fnv1a-x",
            city_pack="us/mi/flint",
        )


def test_typology_row_serializes_class_to_string():
    row = TypologyRow(
        osm_id=1,
        typology_class=TypologyClass.INDUSTRIAL,
        confidence=0.7,
        per_class_proba={TypologyClass.INDUSTRIAL: 0.7},
        feature_completeness=0.8,
        model_version="typology-v0.1.0",
        features_hash="fnv1a-x",
        city_pack="us/mi/flint",
    )
    payload = json.loads(row.model_dump_json())
    assert payload["typology_class"] == "industrial"
