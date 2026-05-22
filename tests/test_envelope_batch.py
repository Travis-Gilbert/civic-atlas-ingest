from __future__ import annotations

from civic_atlas_ingest.envelope_batch import (
    build_edge_spotcheck_report,
    compute_current_envelope_batch,
)
from civic_atlas_ingest.parcel_sources import ParcelEnvelopeInput
from civic_atlas_ingest.zoning_ingest import current_flint_zoning_rules

SOUTH_ROAD = {
    "type": "LineString",
    "coordinates": [[-83.7002, 42.9999], [-83.6986, 42.9999]],
}
WEST_ROAD = {
    "type": "LineString",
    "coordinates": [[-83.70015, 42.9999], [-83.70015, 43.0010]],
}


def _parcel(parcel_key: str, zoning_code: str = "TN-2") -> ParcelEnvelopeInput:
    return ParcelEnvelopeInput(
        parcel_key=parcel_key,
        pid_dash=parcel_key,
        zoning_code=zoning_code,
        land_use="Residential",
        source_fid=parcel_key,
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


def test_compute_current_envelope_batch_writes_assets_and_is_idempotent(tmp_path) -> None:
    rules = {rule.zoning_code: rule for rule in current_flint_zoning_rules()}
    parcels = (_parcel("40-01"), _parcel("40-02"))

    first = compute_current_envelope_batch(
        parcels=parcels,
        rules_by_code=rules,
        road_geometries=(SOUTH_ROAD,),
        asset_root=tmp_path,
    )
    second = compute_current_envelope_batch(
        parcels=parcels,
        rules_by_code=rules,
        road_geometries=(SOUTH_ROAD,),
        asset_root=tmp_path,
    )

    assert first.row_count == 2
    assert first.skipped_count == 0
    assert first.asset_count == 2
    assert first.content_hash == second.content_hash
    for row in first.rows:
        assert row.envelope.scenario_id == "current"
        assert row.envelope.asset_uri == f"sha256://{row.glb_sha256}"
        assert row.glb_asset_path is not None
        assert (tmp_path / row.glb_asset_path).exists()


def test_compute_current_envelope_batch_skips_unknown_zoning_code() -> None:
    rules = {rule.zoning_code: rule for rule in current_flint_zoning_rules()}

    result = compute_current_envelope_batch(
        parcels=(_parcel("40-03", zoning_code="UNKNOWN"),),
        rules_by_code=rules,
        road_geometries=(SOUTH_ROAD,),
    )

    assert result.row_count == 0
    assert result.skipped_count == 1
    assert result.skipped[0].reason == "missing_zoning_rule"


def test_build_edge_spotcheck_report_prefers_corner_lots() -> None:
    report = build_edge_spotcheck_report(
        parcels=(_parcel("40-01"), _parcel("40-02")),
        road_geometries=(SOUTH_ROAD, WEST_ROAD),
        sample_size=2,
    )

    assert report["sample_size"] == 2
    assert report["corner_count"] == 2
    assert report["rows"][0]["front"] == "south"
    assert report["rows"][0]["secondary_front"] == "west"
