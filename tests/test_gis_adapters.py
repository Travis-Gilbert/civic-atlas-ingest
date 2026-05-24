from __future__ import annotations

import httpx

from civic_atlas_ingest.artifact_persistence import build_gis_artifact_envelopes
from civic_atlas_ingest.coverage_quality import ProvenanceLane
from civic_atlas_ingest.gis_adapters import ogc_api_features, stac, wfs
from civic_atlas_ingest.training_corpus import make_training_record


def test_ogc_api_features_adapter_reads_capabilities_and_follows_next_link() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/collections":
            return httpx.Response(
                200,
                json={
                    "collections": [
                        {
                            "id": "parcels",
                            "links": [
                                {"rel": "self", "href": "https://example.test/collections/parcels"}
                            ],
                        }
                    ]
                },
            )
        if request.url.path == "/collections/parcels":
            return httpx.Response(
                200,
                json={
                    "id": "parcels",
                    "title": "Parcels",
                    "item_assets": {"parcel_id": {}, "stories": {}},
                    "links": [
                        {"rel": "items", "href": "https://example.test/collections/parcels/items"}
                    ],
                },
            )
        if request.url.path == "/collections/parcels/items":
            page = request.url.params.get("page", "1")
            if page == "1":
                return httpx.Response(
                    200,
                    json={
                        "type": "FeatureCollection",
                        "features": [
                            {"type": "Feature", "properties": {"parcel_id": "1"}, "geometry": None}
                        ],
                        "links": [
                            {
                                "rel": "next",
                                "href": "https://example.test/collections/parcels/items?page=2",
                            }
                        ],
                    },
                )
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        {"type": "Feature", "properties": {"parcel_id": "2"}, "geometry": None}
                    ],
                    "links": [],
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    capabilities = ogc_api_features.read_capabilities("https://example.test/collections", client=client)
    features = list(
        ogc_api_features.fetch_all_features("https://example.test/collections", client=client)
    )

    assert capabilities.collection_id == "parcels"
    assert capabilities.field_names == ("parcel_id", "stories")
    assert [feature["properties"]["parcel_id"] for feature in features] == ["1", "2"]


def test_ogc_api_features_adapter_uses_collection_hint_for_multi_collection_catalog() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/collections":
            return httpx.Response(
                200,
                json={
                    "collections": [
                        {
                            "id": "zoning",
                            "title": "Zoning districts",
                            "links": [
                                {"rel": "self", "href": "https://example.test/collections/zoning"}
                            ],
                        },
                        {
                            "id": "parcels",
                            "title": "Parcels",
                            "links": [
                                {"rel": "self", "href": "https://example.test/collections/parcels"}
                            ],
                        },
                    ]
                },
            )
        if request.url.path == "/collections/parcels":
            return httpx.Response(
                200,
                json={
                    "id": "parcels",
                    "title": "Parcels",
                    "links": [
                        {"rel": "items", "href": "https://example.test/collections/parcels/items"}
                    ],
                },
            )
        if request.url.path == "/collections/parcels/items":
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        {"type": "Feature", "properties": {"parcel_id": "1"}, "geometry": None}
                    ],
                    "links": [],
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    capabilities = ogc_api_features.read_capabilities(
        "https://example.test/collections",
        collection_hint="Parcel layer",
        client=client,
    )
    features = list(
        ogc_api_features.fetch_all_features(
            "https://example.test/collections",
            collection_hint="Parcel layer",
            client=client,
        )
    )

    assert capabilities.collection_id == "parcels"
    assert [feature["properties"]["parcel_id"] for feature in features] == ["1"]


def test_wfs_adapter_reads_capabilities_and_pages_json_features() -> None:
    capabilities_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:ows="http://www.opengis.net/ows/1.1">
      <ows:ServiceIdentification>
        <ows:Title>City Parcels</ows:Title>
      </ows:ServiceIdentification>
      <wfs:FeatureTypeList>
        <wfs:FeatureType>
          <wfs:Name>atlas:parcels</wfs:Name>
        </wfs:FeatureType>
      </wfs:FeatureTypeList>
      <ows:OperationsMetadata>
        <ows:Constraint name="PagingIsTransactionSafe">
          <ows:DefaultValue>true</ows:DefaultValue>
        </ows:Constraint>
      </ows:OperationsMetadata>
    </wfs:WFS_Capabilities>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("request") == "GetCapabilities":
            return httpx.Response(200, text=capabilities_xml)
        start_index = int(request.url.params.get("startIndex", "0"))
        if start_index == 0:
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        {"type": "Feature", "properties": {"parcel_id": "1"}, "geometry": None},
                        {"type": "Feature", "properties": {"parcel_id": "2"}, "geometry": None},
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {"parcel_id": "3"}, "geometry": None}
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    capabilities = wfs.read_capabilities("https://example.test/geoserver/wfs", client=client)
    features = list(wfs.fetch_all_features("https://example.test/geoserver/wfs", page_size=2, client=client))

    assert capabilities.service_title == "City Parcels"
    assert capabilities.default_feature_type == "atlas:parcels"
    assert [feature["properties"]["parcel_id"] for feature in features] == ["1", "2", "3"]


def test_wfs_adapter_stops_after_first_page_when_paging_is_not_advertised() -> None:
    capabilities_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:ows="http://www.opengis.net/ows/1.1">
      <ows:ServiceIdentification>
        <ows:Title>City Parcels</ows:Title>
      </ows:ServiceIdentification>
      <wfs:FeatureTypeList>
        <wfs:FeatureType>
          <wfs:Name>atlas:parcels</wfs:Name>
        </wfs:FeatureType>
      </wfs:FeatureTypeList>
    </wfs:WFS_Capabilities>
    """
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        if request.url.params.get("request") == "GetCapabilities":
            return httpx.Response(200, text=capabilities_xml)
        request_count += 1
        assert "startIndex" not in request.url.params
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {"parcel_id": "1"}, "geometry": None},
                    {"type": "Feature", "properties": {"parcel_id": "2"}, "geometry": None},
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    features = list(wfs.fetch_all_features("https://example.test/geoserver/wfs", page_size=2, client=client))

    assert request_count == 1
    assert [feature["properties"]["parcel_id"] for feature in features] == ["1", "2"]


def test_stac_adapter_uses_search_link_and_follows_next_link() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/stac":
            return httpx.Response(
                200,
                json={
                    "stac_version": "1.0.0",
                    "id": "flint-catalog",
                    "title": "Flint Catalog",
                    "links": [{"rel": "search", "href": "https://example.test/stac/search"}],
                },
            )
        if request.url.path == "/stac/search":
            page = request.url.params.get("page", "1")
            if page == "1":
                return httpx.Response(
                    200,
                    json={
                        "type": "FeatureCollection",
                        "features": [
                            {"type": "Feature", "properties": {"parcel_id": "1"}, "geometry": None}
                        ],
                        "links": [{"rel": "next", "href": "https://example.test/stac/search?page=2"}],
                    },
                )
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        {"type": "Feature", "properties": {"parcel_id": "2"}, "geometry": None}
                    ],
                    "links": [],
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    capabilities = stac.read_capabilities("https://example.test/stac", client=client)
    features = list(stac.fetch_all_features("https://example.test/stac", client=client))

    assert capabilities.catalog_id == "flint-catalog"
    assert capabilities.item_url == "https://example.test/stac/search"
    assert [feature["properties"]["parcel_id"] for feature in features] == ["1", "2"]


def test_build_gis_artifact_envelopes_produces_gis_feature_payload() -> None:
    record = make_training_record(
        source="assessor",
        source_id="40-01-154-012",
        city="flint",
        geometry={
            "type": "Polygon",
            "coordinates": [[[-83.694, 43.02], [-83.693, 43.02], [-83.693, 43.021], [-83.694, 43.02]]],
        },
        fields={
            "parcel_id": "40-01-154-012",
            "stories": 2,
            "use_type": "Commercial",
        },
        lanes={
            "parcel_id": ProvenanceLane.AUTHORITATIVE_RECENT,
            "stories": ProvenanceLane.AUTHORITATIVE_RECENT,
            "use_type": ProvenanceLane.AUTHORITATIVE_RECENT,
        },
        source_uri="https://example.test/collections/parcels/items",
        extra={"assessor_row": {"PIDdash": "40-01-154-012", "Use_Type": "Commercial"}},
    )

    envelopes = build_gis_artifact_envelopes(
        [record],
        source_class="ogc_api_features",
        source_uri="https://example.test/collections/parcels/items",
        capabilities={"collection_id": "parcels"},
        city="flint",
    )

    assert len(envelopes) == 1
    envelope = envelopes[0]
    assert envelope.source_type == "gis_feature"
    assert envelope.parcel_ref == "40-01-154-012"
    assert "POLYGON" in envelope.anchor_geometry_wkt
    assert '"source_layer": "parcels"' in envelope.payload_json
