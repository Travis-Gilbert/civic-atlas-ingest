from __future__ import annotations

import struct

import pytest

from civic_atlas_ingest.envelope_compute import (
    CardinalEdgeClassification,
    compute_buildable_envelope_result,
    compute_buildable_envelope_seed,
)
from civic_atlas_ingest.zoning_ingest import current_flint_zoning_rules, feet
from civic_atlas_ingest.zoning_schema import ZoningRuleRecord

RECTANGLE = {
    "type": "Polygon",
    "coordinates": [
        [
            [-83.7000, 43.0000],
            [-83.6988, 43.0000],
            [-83.6988, 43.0009],
            [-83.7000, 43.0009],
            [-83.7000, 43.0000],
        ]
    ],
}


def test_compute_buildable_envelope_seed_applies_height_and_setbacks() -> None:
    rule = {rule.zoning_code: rule for rule in current_flint_zoning_rules()}["TN-2"]

    envelope = compute_buildable_envelope_seed(
        parcel_key="fixture-tn-2",
        parcel_geometry=RECTANGLE,
        rule=rule,
        edges=CardinalEdgeClassification(front="south", rear="north"),
        existing_floor_area_m2=200.0,
    )

    assert envelope.zoning_code == "TN-2"
    assert envelope.max_height_m == feet(35)
    assert envelope.max_stories == 2.5
    assert envelope.binding_constraint == "coverage"
    assert envelope.buildable_floor_area_m2 is not None
    assert envelope.headroom_floor_area_m2 is not None
    assert envelope.headroom_floor_area_m2 > 0
    assert envelope.max_units_estimated is not None
    assert envelope.max_units_estimated > 0
    assert envelope.envelope_geometry["coordinates"][0][0][2] == feet(35)
    assert envelope.content_hash is not None
    assert envelope.asset_uri == f"sha256://{envelope.content_hash}"


def test_compute_buildable_envelope_seed_uses_far_when_more_restrictive() -> None:
    rule = ZoningRuleRecord(
        city_pack="flint",
        rule_id="fixture-far",
        zoning_code="FX",
        max_height_m=feet(100),
        max_stories=20,
        max_far=1.0,
        min_front_setback_m=0,
        min_side_setback_m=0,
        min_rear_setback_m=0,
        allowed_uses=("mixed_use",),
    )

    envelope = compute_buildable_envelope_seed(
        parcel_key="fixture-far",
        parcel_geometry=RECTANGLE,
        rule=rule,
        edges=CardinalEdgeClassification(front="south", rear="north"),
    )

    assert envelope.binding_constraint == "far"
    assert envelope.max_height_m < feet(100)
    assert envelope.metrics["floors_for_gfa"] == pytest.approx(1.0)
    assert envelope.max_units_estimated is not None


def test_compute_buildable_envelope_result_exports_valid_glb_header() -> None:
    rule = {rule.zoning_code: rule for rule in current_flint_zoning_rules()}["TN-2"]

    result = compute_buildable_envelope_result(
        parcel_key="fixture-tn-2",
        parcel_geometry=RECTANGLE,
        rule=rule,
        edges=CardinalEdgeClassification(front="south", rear="north"),
    )
    magic, version, total_length = struct.unpack("<III", result.glb_bytes[:12])

    assert magic == 0x46546C67
    assert version == 2
    assert total_length == len(result.glb_bytes)
    assert result.seed.content_hash == result.glb_sha256


def test_corner_lot_uses_secondary_front_setback() -> None:
    rule = ZoningRuleRecord(
        city_pack="flint",
        rule_id="fixture-corner",
        zoning_code="FX",
        max_height_m=feet(35),
        min_front_setback_m=30,
        min_side_setback_m=0,
        min_rear_setback_m=0,
        allowed_uses=("residential",),
    )

    interior = compute_buildable_envelope_seed(
        parcel_key="fixture-interior",
        parcel_geometry=RECTANGLE,
        rule=rule,
        edges=CardinalEdgeClassification(front="south", rear="north"),
    )
    corner = compute_buildable_envelope_seed(
        parcel_key="fixture-corner",
        parcel_geometry=RECTANGLE,
        rule=rule,
        edges=CardinalEdgeClassification(
            front="south",
            rear="north",
            secondary_front="west",
            is_corner=True,
        ),
    )

    assert corner.metrics["buildable_footprint_area_m2"] < interior.metrics[
        "buildable_footprint_area_m2"
    ]


def test_compute_buildable_envelope_seed_rejects_excessive_setbacks() -> None:
    rule = ZoningRuleRecord(
        city_pack="flint",
        rule_id="fixture-setbacks",
        zoning_code="FX",
        max_height_m=feet(35),
        min_front_setback_m=200,
        min_side_setback_m=200,
        min_rear_setback_m=200,
        allowed_uses=("residential",),
    )

    with pytest.raises(ValueError, match="setbacks exceed"):
        compute_buildable_envelope_seed(
            parcel_key="fixture-setbacks",
            parcel_geometry=RECTANGLE,
            rule=rule,
            edges=CardinalEdgeClassification(front="south", rear="north"),
        )


def test_non_residential_rule_has_no_unit_estimate() -> None:
    rule = ZoningRuleRecord(
        city_pack="flint",
        rule_id="fixture-industrial",
        zoning_code="FX",
        max_height_m=feet(35),
        min_front_setback_m=0,
        min_side_setback_m=0,
        min_rear_setback_m=0,
        allowed_uses=("industrial",),
    )

    envelope = compute_buildable_envelope_seed(
        parcel_key="fixture-industrial",
        parcel_geometry=RECTANGLE,
        rule=rule,
        edges=CardinalEdgeClassification(front="south", rear="north"),
    )

    assert envelope.max_units_estimated is None
