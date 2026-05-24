"""WFS adapter for public feature services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from xml.etree import ElementTree

import httpx

from civic_atlas_ingest.zoning_sources import HTTP_HEADERS


@dataclass(frozen=True)
class CapabilitiesDocument:
    endpoint_url: str
    service_title: str
    feature_type_names: tuple[str, ...]
    default_feature_type: str
    supports_pagination: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "endpoint_url": self.endpoint_url,
            "service_title": self.service_title,
            "feature_type_names": list(self.feature_type_names),
            "default_feature_type": self.default_feature_type,
            "supports_pagination": self.supports_pagination,
        }


def read_capabilities(
    endpoint_url: str,
    *,
    timeout_s: float = 30.0,
    client: httpx.Client | None = None,
) -> CapabilitiesDocument:
    def run(active_client: httpx.Client) -> CapabilitiesDocument:
        response = active_client.get(_capabilities_url(endpoint_url))
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        feature_types = tuple(_feature_type_names(root))
        return CapabilitiesDocument(
            endpoint_url=endpoint_url,
            service_title=_service_title(root) or endpoint_url,
            feature_type_names=feature_types,
            default_feature_type=_default_feature_type(endpoint_url, feature_types),
            supports_pagination=_supports_pagination(root),
        )

    if client is not None:
        return run(client)
    with httpx.Client(timeout=timeout_s, follow_redirects=True, headers=HTTP_HEADERS) as active_client:
        return run(active_client)


def fetch_all_features(
    endpoint_url: str,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    page_size: int = 200,
    limit: int | None = None,
    timeout_s: float = 30.0,
    client: httpx.Client | None = None,
) -> Iterator[dict[str, Any]]:
    def generate(active_client: httpx.Client) -> Iterator[dict[str, Any]]:
        capabilities = read_capabilities(endpoint_url, client=active_client)
        type_name = capabilities.default_feature_type
        if not type_name:
            return
        yielded = 0
        start_index = 0

        while True:
            remaining = None if limit is None else max(limit - yielded, 0)
            if remaining == 0:
                return
            count = page_size if remaining is None else min(page_size, remaining)
            params: dict[str, Any] = {
                "service": "WFS",
                "request": "GetFeature",
                "version": "2.0.0",
                "typeNames": type_name,
                "outputFormat": "application/json",
                "srsName": "EPSG:4326",
                "count": count,
            }
            if bbox is not None:
                params["bbox"] = ",".join(str(value) for value in bbox) + ",EPSG:4326"
            if capabilities.supports_pagination:
                params["startIndex"] = start_index
            payload = _fetch_feature_json(active_client, endpoint_url, params)
            features = payload.get("features", [])
            if not isinstance(features, list) or not features:
                return
            for feature in features:
                if isinstance(feature, dict):
                    yield feature
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return
            if not capabilities.supports_pagination or len(features) < count:
                return
            start_index += len(features)

    if client is not None:
        yield from generate(client)
        return
    with httpx.Client(timeout=timeout_s, follow_redirects=True, headers=HTTP_HEADERS) as active_client:
        yield from generate(active_client)


def _capabilities_url(endpoint_url: str) -> str:
    return _replace_query_params(
        endpoint_url,
        {
            "service": "WFS",
            "request": "GetCapabilities",
        },
    )


def _fetch_feature_json(
    client: httpx.Client,
    endpoint_url: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    response = client.get(endpoint_url, params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON from {response.url}")
    return payload


def _replace_query_params(url: str, params: dict[str, Any]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in params.items()})
    return urlunparse(parsed._replace(query=urlencode(query)))


def _feature_type_names(root: ElementTree.Element) -> list[str]:
    names: list[str] = []
    for parent in root.iter():
        if not parent.tag.lower().endswith("featuretype"):
            continue
        for child in parent:
            if child.tag.lower().endswith("name"):
                text = (child.text or "").strip()
                if text:
                    names.append(text)
    return names


def _service_title(root: ElementTree.Element) -> str:
    for parent in root.iter():
        if not parent.tag.lower().endswith("serviceidentification"):
            continue
        for child in parent:
            if child.tag.lower().endswith("title"):
                return (child.text or "").strip()
    return ""


def _default_feature_type(endpoint_url: str, feature_types: tuple[str, ...]) -> str:
    parsed = urlparse(endpoint_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key in ("typeNames", "typenames", "typeName", "typename"):
        value = str(query.get(key) or "").strip()
        if value:
            return value
    return feature_types[0] if feature_types else ""


def _supports_pagination(root: ElementTree.Element) -> bool:
    for element in root.iter():
        tag = element.tag.lower()
        if tag.endswith("constraint"):
            name = str(element.attrib.get("name") or "").lower()
            if name in {"pagingistransactionsafe", "countdefault", "startindex"}:
                return True
    return False
