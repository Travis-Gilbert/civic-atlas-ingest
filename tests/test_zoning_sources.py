from __future__ import annotations

import hashlib

from civic_atlas_ingest.zoning_sources import (
    FLINT_PARCEL_GEOMETRY_LAYER_URL,
    FLINT_PARCEL_ZONING_TABLE_URL,
    PARCEL_GEOMETRY_FIELDS,
    PARCEL_ZONING_FIELDS,
    SourceSnapshot,
    ZoningSourceRef,
    build_arcgis_query_url,
    flint_zoning_source_refs,
    layer_probe_from_metadata,
    parcel_geometry_query_url,
    parcel_zoning_join_probe_from_payloads,
    parcel_zoning_query_url,
)


def test_flint_sources_are_public_http_refs_without_sdk_dependency() -> None:
    refs = flint_zoning_source_refs()
    urls = {ref.url for ref in refs}

    assert "https://www.cityofflint.com/zoning-division/" in urls
    assert f"{FLINT_PARCEL_GEOMETRY_LAYER_URL}?f=pjson" in urls
    assert f"{FLINT_PARCEL_ZONING_TABLE_URL}?f=pjson" in urls
    assert all(ref.url.startswith("https://") for ref in refs)
    assert all("arcgis.com/home" not in ref.url for ref in refs)


def test_arcgis_query_urls_are_plain_http_queries() -> None:
    url = build_arcgis_query_url(
        FLINT_PARCEL_GEOMETRY_LAYER_URL,
        {
            "where": "PIDdash IS NOT NULL",
            "outFields": ",".join(PARCEL_GEOMETRY_FIELDS),
            "returnGeometry": True,
            "f": "geojson",
        },
    )

    assert url.startswith(f"{FLINT_PARCEL_GEOMETRY_LAYER_URL}/query?")
    assert "where=PIDdash+IS+NOT+NULL" in url
    assert "returnGeometry=true" in url
    assert "f=geojson" in url


def test_layer_probe_reports_missing_fields_and_pagination() -> None:
    metadata = {
        "fields": [{"name": "PIDdash"}, {"name": "Zoning"}],
        "maxRecordCount": 2000,
        "advancedQueryCapabilities": {"supportsPagination": True},
    }

    probe = layer_probe_from_metadata(
        key="flint-parcel-geometry-layer",
        url=FLINT_PARCEL_GEOMETRY_LAYER_URL,
        query_url=parcel_geometry_query_url(2),
        metadata=metadata,
        required_fields=PARCEL_GEOMETRY_FIELDS,
    )

    assert probe.supports_pagination is True
    assert probe.max_record_count == 2000
    assert "PIDdash" in probe.observed_fields
    assert probe.missing_fields == ("FID", "PIDText", "LandUse")


def test_parcel_zoning_join_probe_matches_pid_dash_rows() -> None:
    parcel_payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "FID": 1,
                    "PIDdash": "40-01-154-012",
                    "PIDText": "4001154012",
                    "Zoning": "GN-1",
                    "LandUse": "Green Neighborhood",
                },
                "geometry": {"type": "Polygon", "coordinates": []},
            },
            {
                "type": "Feature",
                "properties": {
                    "FID": 2,
                    "PIDdash": "40-01-154-013",
                    "PIDText": "4001154013",
                    "Zoning": "GN-1",
                    "LandUse": "Green Neighborhood",
                },
                "geometry": {"type": "Polygon", "coordinates": []},
            },
        ],
    }
    zoning_payload = {
        "features": [
            {
                "attributes": {
                    "FID2": 77,
                    "PIDdash": "40-01-154-012",
                    "Current_Zoning": "GN-1",
                    "Current_Landuse": "Green Neighborhood",
                    "Previous_Zoning": "A-2",
                    "Ward": 2,
                }
            },
            {
                "attributes": {
                    "FID2": 105,
                    "PIDdash": "40-01-154-013",
                    "Current_Zoning": "GN-1",
                    "Current_Landuse": "Green Neighborhood",
                    "Previous_Zoning": "A-2",
                    "Ward": 2,
                }
            },
        ]
    }

    probe = parcel_zoning_join_probe_from_payloads(
        parcel_query_url=parcel_geometry_query_url(2),
        zoning_query_url=parcel_zoning_query_url(("40-01-154-012", "40-01-154-013")),
        parcel_payload=parcel_payload,
        zoning_payload=zoning_payload,
    )

    assert probe.sample_size == 2
    assert probe.joined_count == 2
    assert probe.missing_pid_count == 0
    assert probe.mismatched_count == 0
    assert probe.rows[0].zoning_matches is True
    assert probe.rows[1].land_use_matches is True


def test_source_snapshot_shape_uses_sha256() -> None:
    body = b"source bytes"
    snapshot = SourceSnapshot(
        key="fixture",
        label="Fixture",
        url="https://example.test/source.pdf",
        final_url="https://example.test/source.pdf",
        kind="pdf",
        status_code=200,
        content_type="application/pdf",
        byte_count=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
    )

    assert snapshot.sha256 == "4d4823794cbed3c4ee0bbc684c8f66e1dfd5afa6f078d494ce254ec5a4671753"
    assert snapshot.byte_count == 12


def test_zoning_source_ref_can_name_required_fields() -> None:
    ref = ZoningSourceRef(
        key="fielded",
        label="Fielded",
        url="https://example.test/layer?f=pjson",
        kind="arcgis-rest-metadata",
        required_fields=PARCEL_ZONING_FIELDS,
    )

    assert "Current_Zoning" in ref.required_fields
