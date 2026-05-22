from __future__ import annotations

from datetime import UTC, datetime

from civic_atlas_ingest.envelope_batch import compute_current_envelope_batch
from civic_atlas_ingest.parcel_sources import ParcelEnvelopeInput
from civic_atlas_ingest.scenario_recompute import recompute_scenario_envelopes
from civic_atlas_ingest.scenario_schema import ScenarioZoningOverride
from civic_atlas_ingest.zoning_ingest import current_flint_zoning_rules

SOUTH_ROAD = {
    "type": "LineString",
    "coordinates": [[-83.7002, 42.9999], [-83.6986, 42.9999]],
}


def _parcel(parcel_key: str, x_offset: float) -> ParcelEnvelopeInput:
    return ParcelEnvelopeInput(
        parcel_key=parcel_key,
        pid_dash=parcel_key,
        zoning_code="TN-2",
        land_use="Residential",
        source_fid=parcel_key,
        geometry={
            "type": "Polygon",
            "coordinates": [
                [
                    [-83.7000 + x_offset, 43.0000],
                    [-83.6988 + x_offset, 43.0000],
                    [-83.6988 + x_offset, 43.0009],
                    [-83.7000 + x_offset, 43.0009],
                    [-83.7000 + x_offset, 43.0000],
                ]
            ],
        },
    )


def test_recompute_scenario_envelopes_only_rewrites_dirty_parcels() -> None:
    rules = {rule.zoning_code: rule for rule in current_flint_zoning_rules()}
    parcels = (_parcel("40-01", 0), _parcel("40-02", 0.004))
    current = compute_current_envelope_batch(
        parcels=parcels,
        rules_by_code=rules,
        road_geometries=(SOUTH_ROAD,),
    )
    override = ScenarioZoningOverride(
        city_pack="flint",
        scenario_id="upzone",
        override_id="height-boost",
        geometry=parcels[0].geometry,
        created_at=datetime.now(UTC),
        created_by="planner",
        rule_patch={"max_height_m": 18.0},
    )

    result = recompute_scenario_envelopes(
        scenario_id="upzone",
        parcels=parcels,
        rules_by_code=rules,
        road_geometries=(SOUTH_ROAD,),
        base_envelopes=current.rows,
        zoning_overrides=(override,),
    )

    assert result.dirty_parcel_keys == ("40-01",)
    assert result.recomputed.row_count == 1
    assert result.recomputed.rows[0].parcel_key == "40-01"
    assert result.recomputed.rows[0].envelope.max_height_m == 18.0
    assert len(result.inherited) == 1
    assert result.inherited[0].parcel_key == "40-02"
    assert result.content_hash
