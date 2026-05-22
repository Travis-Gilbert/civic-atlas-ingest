from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from civic_atlas_ingest.zoning_schema import (
    BuildableEnvelopeSeed,
    ZoningBoundarySeed,
    ZoningRuleRecord,
    ZoningSourceSnapshotRecord,
)

POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-83.709354, 43.041493],
            [-83.709206, 43.041495],
            [-83.7092, 43.041192],
            [-83.709345, 43.041189],
            [-83.709354, 43.041493],
        ]
    ],
}

POLYGON_Z = {
    "type": "Polygon",
    "coordinates": [
        [
            [-83.709354, 43.041493, 0.0],
            [-83.709206, 43.041495, 12.0],
            [-83.7092, 43.041192, 12.0],
            [-83.709345, 43.041189, 0.0],
            [-83.709354, 43.041493, 0.0],
        ]
    ],
}


def test_zoning_source_snapshot_accepts_public_source_hash() -> None:
    record = ZoningSourceSnapshotRecord(
        city_pack="flint",
        source_key="flint-zoning-code-2025-v1-5-1",
        source_url="https://www.cityofflint.com/example.pdf",
        source_kind="pdf",
        retrieved_at=datetime.now(UTC),
        content_sha256="a" * 64,
        byte_count=123,
    )

    assert record.city_pack == "flint"


def test_zoning_rule_validates_massing_and_confidence() -> None:
    record = ZoningRuleRecord(
        city_pack="flint",
        rule_id="flint-gn-1-current",
        zoning_code="GN-1",
        max_height_m=10.67,
        max_stories=2.5,
        max_far=1.5,
        max_lot_coverage=0.6,
        allowed_uses=("residential", "civic"),
        conditional_uses=("commercial",),
        valid_from=date(2025, 2, 6),
        confidence=0.85,
    )

    assert record.zoning_code == "GN-1"


def test_zoning_rule_rejects_invalid_dates() -> None:
    with pytest.raises(ValueError, match="valid_to"):
        ZoningRuleRecord(
            city_pack="flint",
            rule_id="bad-date",
            zoning_code="GN-1",
            valid_from=date(2026, 1, 1),
            valid_to=date(2025, 1, 1),
        )


def test_boundary_seed_keeps_current_scenario_default_explicit() -> None:
    boundary = ZoningBoundarySeed(
        city_pack="flint",
        scenario_id="current",
        parcel_key="40-01-154-012",
        pid_dash="40-01-154-012",
        zoning_code="GN-1",
        land_use="Green Neighborhood",
        geometry=POLYGON,
    )

    assert boundary.scenario_id == "current"


def test_envelope_seed_requires_non_negative_metrics() -> None:
    envelope = BuildableEnvelopeSeed(
        city_pack="flint",
        scenario_id="current",
        parcel_key="40-01-154-012",
        zoning_code="GN-1",
        base_geometry=POLYGON,
        envelope_geometry=POLYGON_Z,
        max_height_m=10.67,
        max_stories=2.5,
        max_far=1.5,
        buildable_floor_area_m2=900.0,
        existing_floor_area_m2=250.0,
        headroom_floor_area_m2=650.0,
        max_units_estimated=8,
        binding_constraint="height",
    )

    assert envelope.headroom_floor_area_m2 == 650.0
    assert envelope.max_stories == 2.5
    assert envelope.max_units_estimated == 8


def test_envelope_seed_rejects_negative_height() -> None:
    with pytest.raises(ValueError, match="max_height_m"):
        BuildableEnvelopeSeed(
            city_pack="flint",
            scenario_id="current",
            parcel_key="40-01-154-012",
            zoning_code="GN-1",
            base_geometry=POLYGON,
            envelope_geometry=POLYGON_Z,
            max_height_m=-1,
        )
