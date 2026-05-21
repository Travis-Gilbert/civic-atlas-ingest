from __future__ import annotations

from civic_atlas_ingest.city_targets import get_target
from civic_atlas_ingest.ingest_assessor import _records_from_assessor_payload
from civic_atlas_ingest.ingest_overpass import _records_from_overpass


def test_overpass_fixture_becomes_training_record() -> None:
    target = get_target("flint")
    payload = {
        "elements": [
            {
                "type": "way",
                "id": 123,
                "tags": {
                    "building": "commercial",
                    "building:levels": "2",
                    "building:material": "brick",
                    "roof:shape": "flat",
                },
                "geometry": [
                    {"lat": 43.0, "lon": -83.7},
                    {"lat": 43.0, "lon": -83.69},
                    {"lat": 43.01, "lon": -83.69},
                    {"lat": 43.0, "lon": -83.7},
                ],
            }
        ]
    }

    records = _records_from_overpass(payload, target=target, source_uri="fixture", limit=10)

    assert len(records) == 1
    assert records[0].archetype_label == "commercial-brick-two-story"
    assert records[0].part_labels["facade"]["material"] == "brick"


def test_regrid_payload_becomes_assessor_records() -> None:
    payload = {
        "kind": "regrid_tilejson_sample",
        "grid": {
            "data": {
                "0": {
                    "fid": 1,
                    "parcelnumb": "40-12-48-0003",
                    "address": "607 E 2ND AVE",
                    "owner": "Private owner",
                    "geojson": (
                        '{"type":"Polygon","coordinates":[[[-83.694,43.020],'
                        '[-83.693,43.020],[-83.693,43.021],[-83.694,43.020]]]}'
                    ),
                }
            }
        },
    }

    records = _records_from_assessor_payload(
        payload,
        city="flint",
        source_uri="https://tiles.regrid.com/api/v1/parcels/mi_genesee_flint20251129",
        limit=5,
    )

    assert len(records) == 1
    assert records[0].source_id == "40-12-48-0003"
    assert records[0].coverage.quality == 1.0
    assert "owner" not in records[0].extra["assessor_row"]
