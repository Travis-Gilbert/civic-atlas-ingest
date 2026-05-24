"""STAC adapter for item collections and search endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urljoin

import httpx

from civic_atlas_ingest.zoning_sources import HTTP_HEADERS


@dataclass(frozen=True)
class CapabilitiesDocument:
    endpoint_url: str
    catalog_id: str
    title: str
    item_url: str
    collection_id: str
    supports_pagination: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "endpoint_url": self.endpoint_url,
            "catalog_id": self.catalog_id,
            "title": self.title,
            "item_url": self.item_url,
            "collection_id": self.collection_id,
            "supports_pagination": self.supports_pagination,
        }


def read_capabilities(
    endpoint_url: str,
    *,
    timeout_s: float = 30.0,
    client: httpx.Client | None = None,
) -> CapabilitiesDocument:
    def run(active_client: httpx.Client) -> CapabilitiesDocument:
        payload = _fetch_json(active_client, endpoint_url)
        item_url, collection_id = _item_url(payload, endpoint_url)
        return CapabilitiesDocument(
            endpoint_url=endpoint_url,
            catalog_id=str(payload.get("id") or collection_id or endpoint_url),
            title=str(payload.get("title") or payload.get("id") or endpoint_url),
            item_url=item_url,
            collection_id=collection_id,
            supports_pagination=True,
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
        next_url = capabilities.item_url
        yielded = 0
        next_params: dict[str, Any] | None = {"limit": page_size}
        if capabilities.collection_id and "/search" in next_url:
            next_params["collections"] = capabilities.collection_id
        if bbox is not None:
            next_params["bbox"] = ",".join(str(value) for value in bbox)

        while next_url:
            remaining = None if limit is None else max(limit - yielded, 0)
            if remaining == 0:
                return
            params = None if next_params is None else dict(next_params)
            if remaining is not None and params is not None and "limit" in params:
                params["limit"] = min(int(params["limit"]), remaining)
            payload = _fetch_json(active_client, next_url, params=params)
            features = payload.get("features", [])
            if not isinstance(features, list) or not features:
                return
            for feature in features:
                if isinstance(feature, dict):
                    yield feature
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return
            next_url = _next_link(payload, next_url)
            next_params = None

    if client is not None:
        yield from generate(client)
        return
    with httpx.Client(timeout=timeout_s, follow_redirects=True, headers=HTTP_HEADERS) as active_client:
        yield from generate(active_client)


def _item_url(payload: dict[str, Any], endpoint_url: str) -> tuple[str, str]:
    collection_id = ""
    for link in payload.get("links", []):
        if not isinstance(link, dict):
            continue
        rel = str(link.get("rel") or "").lower()
        href = str(link.get("href") or "").strip()
        if rel == "search" and href:
            return urljoin(endpoint_url.rstrip("/") + "/", href), collection_id
        if rel == "items" and href:
            return urljoin(endpoint_url.rstrip("/") + "/", href), str(payload.get("id") or "")
        if rel == "child" and href and not collection_id:
            child_url = urljoin(endpoint_url.rstrip("/") + "/", href)
            child_id = child_url.rstrip("/").split("/")[-1]
            return urljoin(child_url.rstrip("/") + "/", "items"), child_id
    if endpoint_url.rstrip("/").endswith("/items"):
        return endpoint_url, str(payload.get("id") or "")
    return endpoint_url.rstrip("/") + "/items", collection_id


def _next_link(payload: dict[str, Any], base_url: str) -> str | None:
    for link in payload.get("links", []):
        if not isinstance(link, dict):
            continue
        rel = str(link.get("rel") or "").lower()
        href = str(link.get("href") or "").strip()
        if rel == "next" and href:
            return urljoin(base_url.rstrip("/") + "/", href)
    return None


def _fetch_json(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.get(url, params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON from {response.url}")
    return payload
