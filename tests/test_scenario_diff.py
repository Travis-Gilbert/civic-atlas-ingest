from __future__ import annotations

from dataclasses import replace

from civic_atlas_ingest.envelope_batch import compute_current_envelope_batch
from civic_atlas_ingest.parcel_sources import ParcelEnvelopeInput
from civic_atlas_ingest.scenario_diff import diff_envelope_records
from civic_atlas_ingest.zoning_ingest import current_flint_zoning_rules

SOUTH_ROAD = {
    "type": "LineString",
    "coordinates": [[-83.7002, 42.9999], [-83.6986, 42.9999]],
}


def test_diff_envelope_records_returns_changed_parcels_only() -> None:
    rules = {rule.zoning_code: rule for rule in current_flint_zoning_rules()}
    parcel = ParcelEnvelopeInput(
        parcel_key="40-01",
        pid_dash="40-01",
        zoning_code="TN-2",
        land_use="Residential",
        source_fid="40-01",
        geometry={
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
        },
    )
    current = compute_current_envelope_batch(
        parcels=(parcel,),
        rules_by_code=rules,
        road_geometries=(SOUTH_ROAD,),
    )
    target_row = replace(
        current.rows[0],
        envelope=replace(
            current.rows[0].envelope,
            scenario_id="upzone",
            max_height_m=current.rows[0].envelope.max_height_m + 4.0,
            max_units_estimated=(current.rows[0].envelope.max_units_estimated or 0) + 3,
        ),
    )

    deltas = diff_envelope_records(
        base_scenario_id="current",
        target_scenario_id="upzone",
        base_rows=current.rows,
        target_rows=(target_row,),
    )

    assert len(deltas) == 1
    assert deltas[0].parcel_key == "40-01"
    assert deltas[0].max_height_delta_m == 4.0
    assert deltas[0].unit_delta == 3
