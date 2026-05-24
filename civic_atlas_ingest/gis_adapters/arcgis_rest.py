"""ArcGIS REST adapter for public feature layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import httpx

from civic_atlas_ingest.zoning_sources import HTTP_HEADERS, build_arcgis_query_url


@dataclass(frozen=True)
class CapabilitiesDocument:
    endpoint_url: str
    layer_name: str
    geometry_type: str
    field_names: tuple[str, ...]
    max_record_count: int
    supports_pagination: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "endpoint_url": self.endpoint_url,
            "layer_name": self.layer_name,
            "geometry_type": self.geometry_type,
            "field_names": list(self.field_names),
            "max_record_count": self.max_record_count,
            "supports_pagination": self.supports_pagination,
        }


def read_capabilities(
    endpoint_url: str,
    *,
    timeout_s: float = 30.0,
    client: httpx.Client | None = None,
) -> CapabilitiesDocument:
    def run(active_client: httpx.Client) -> CapabilitiesDocument:
        payload = _fetch_json(active_client, _capabilities_url(endpoint_url))
        fields = tuple(
            str(field.get("name"))
            for field in payload.get("fields", [])
            if isinstance(field, dict) and field.get("name")
        )
        max_record_count = payload.get("maxRecordCount")
        return CapabilitiesDocument(
            endpoint_url=endpoint_url,
            layer_name=str(payload.get("name") or payload.get("serviceDescription") or endpoint_url),
            geometry_type=str(payload.get("geometryType") or ""),
            field_names=fields,
            max_record_count=int(max_record_count) if isinstance(max_record_count, int) else 2000,
            supports_pagination=bool(
                payload.get("advancedQueryCapabilities", {}).get("supportsPagination", False)
            ),
        )

    if client is not None:
        return run(client)
    with httpx.Client(timeout=timeout_s, follow_redirects=True, headers=HTTP_HEADERS) as active_client:
        return run(active_client)


def fetch_all_features(
    endpoint_url: str,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    where: str = "1=1",
    out_fields: str = "*",
    page_size: int | None = None,
    limit: int | None = None,
    timeout_s: float = 30.0,
    client: httpx.Client | None = None,
) -> Iterator[dict[str, Any]]:
    def generate(active_client: httpx.Client) -> Iterator[dict[str, Any]]:
        capabilities = read_capabilities(endpoint_url, client=active_client)
        requested_page_size = page_size or capabilities.max_record_count or 2000
        requested_page_size = max(1, min(requested_page_size, capabilities.max_record_count or requested_page_size))
        offset = 0
        yielded = 0

        while True:
            remaining = None if limit is None else max(limit - yielded, 0)
            if remaining == 0:
                break
            result_record_count = requested_page_size if remaining is None else min(requested_page_size, remaining)
            params: dict[str, str | int | bool] = {
                "where": where,
                "outFields": out_fields,
                "returnGeometry": True,
                "outSR": 4326,
                "resultRecordCount": result_record_count,
                "f": "geojson",
            }
            if capabilities.supports_pagination:
                params["resultOffset"] = offset
            if bbox is not None:
                params["geometry"] = ",".join(str(value) for value in bbox)
                params["geometryType"] = "esriGeometryEnvelope"
                params["inSR"] = 4326
                params["spatialRel"] = "esriSpatialRelIntersects"
            payload = _fetch_json(active_client, build_arcgis_query_url(endpoint_url, params))
            features = payload.get("features", [])
            if not isinstance(features, list) or not features:
                break
            for feature in features:
                if isinstance(feature, dict):
                    yield feature
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return
            if not capabilities.supports_pagination or len(features) < result_record_count:
                break
            offset += len(features)

    if client is not None:
        yield from generate(client)
        return
    with httpx.Client(timeout=timeout_s, follow_redirects=True, headers=HTTP_HEADERS) as active_client:
        yield from generate(active_client)


def _capabilities_url(endpoint_url: str) -> str:
    if "?" in endpoint_url:
        return endpoint_url
    return f"{endpoint_url}?f=pjson"


def _fetch_json(client: httpx.Client, url: str) -> dict[str, Any]:
    response = client.get(url)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON from {url}")
    return payload
