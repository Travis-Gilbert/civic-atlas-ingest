"""OGC API Features adapter for public feature collections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urljoin

import httpx

from civic_atlas_ingest.zoning_sources import HTTP_HEADERS


@dataclass(frozen=True)
class CapabilitiesDocument:
    endpoint_url: str
    collection_id: str
    title: str
    description: str
    item_url: str
    field_names: tuple[str, ...]
    supports_pagination: bool
    supports_bbox: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "endpoint_url": self.endpoint_url,
            "collection_id": self.collection_id,
            "title": self.title,
            "description": self.description,
            "item_url": self.item_url,
            "field_names": list(self.field_names),
            "supports_pagination": self.supports_pagination,
            "supports_bbox": self.supports_bbox,
        }


def read_capabilities(
    endpoint_url: str,
    *,
    collection_hint: str | None = None,
    timeout_s: float = 30.0,
    client: httpx.Client | None = None,
) -> CapabilitiesDocument:
    def run(active_client: httpx.Client) -> CapabilitiesDocument:
        collection_url, collection_doc, item_url = _resolve_collection(
            active_client,
            endpoint_url,
            collection_hint=collection_hint,
        )
        field_names = _field_names(collection_doc)
        return CapabilitiesDocument(
            endpoint_url=endpoint_url,
            collection_id=str(collection_doc.get("id") or ""),
            title=str(collection_doc.get("title") or collection_doc.get("id") or endpoint_url),
            description=str(collection_doc.get("description") or ""),
            item_url=item_url,
            field_names=field_names,
            supports_pagination=True,
            supports_bbox=True,
        )

    if client is not None:
        return run(client)
    with httpx.Client(timeout=timeout_s, follow_redirects=True, headers=HTTP_HEADERS) as active_client:
        return run(active_client)


def fetch_all_features(
    endpoint_url: str,
    *,
    collection_hint: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    page_size: int = 200,
    limit: int | None = None,
    timeout_s: float = 30.0,
    client: httpx.Client | None = None,
) -> Iterator[dict[str, Any]]:
    def generate(active_client: httpx.Client) -> Iterator[dict[str, Any]]:
        capabilities = read_capabilities(
            endpoint_url,
            collection_hint=collection_hint,
            client=active_client,
        )
        next_url = capabilities.item_url
        yielded = 0
        next_params: dict[str, Any] | None = {
            "limit": page_size,
        }
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
            next_url = _next_link(payload, base_url=next_url)
            next_params = None

    if client is not None:
        yield from generate(client)
        return
    with httpx.Client(timeout=timeout_s, follow_redirects=True, headers=HTTP_HEADERS) as active_client:
        yield from generate(active_client)


def _resolve_collection(
    client: httpx.Client,
    endpoint_url: str,
    *,
    collection_hint: str | None = None,
) -> tuple[str, dict[str, Any], str]:
    payload = _fetch_json(client, endpoint_url)
    if isinstance(payload.get("features"), list):
        collection_url = _trim_items_suffix(endpoint_url)
        collection_doc = {
            "id": _collection_id_from_url(collection_url),
            "title": _collection_id_from_url(collection_url),
        }
        return collection_url, collection_doc, endpoint_url

    if isinstance(payload.get("collections"), list):
        collections = [item for item in payload["collections"] if isinstance(item, dict)]
        if not collections:
            raise ValueError(f"no collections advertised by {endpoint_url}")
        selected = _select_collection_entry(
            collections,
            endpoint_url=endpoint_url,
            collection_hint=collection_hint,
        )
        collection_url = _collection_self_url(selected, endpoint_url)
        collection_doc = _fetch_json(client, collection_url)
        return collection_url, collection_doc, _items_url(collection_doc, collection_url)

    collection_url = _normalize_collection_url(endpoint_url)
    collection_doc = payload
    return collection_url, collection_doc, _items_url(collection_doc, collection_url)


def _normalize_collection_url(endpoint_url: str) -> str:
    if endpoint_url.rstrip("/").endswith("/items"):
        return _trim_items_suffix(endpoint_url)
    return endpoint_url


def _trim_items_suffix(url: str) -> str:
    stripped = url.rstrip("/")
    if stripped.endswith("/items"):
        return stripped[: -len("/items")]
    return stripped


def _items_url(collection_doc: dict[str, Any], collection_url: str) -> str:
    for link in collection_doc.get("links", []):
        if not isinstance(link, dict):
            continue
        rel = str(link.get("rel") or "").lower()
        href = str(link.get("href") or "").strip()
        if rel in {"items", "data"} and href:
            return urljoin(collection_url.rstrip("/") + "/", href)
    return collection_url.rstrip("/") + "/items"


def _collection_self_url(collection_doc: dict[str, Any], base_url: str) -> str:
    for link in collection_doc.get("links", []):
        if not isinstance(link, dict):
            continue
        rel = str(link.get("rel") or "").lower()
        href = str(link.get("href") or "").strip()
        if rel == "self" and href:
            return urljoin(base_url.rstrip("/") + "/", href)
    collection_id = str(collection_doc.get("id") or "").strip()
    if collection_id:
        return base_url.rstrip("/") + f"/{collection_id}"
    return base_url


def _collection_id_from_url(url: str) -> str:
    stripped = url.rstrip("/")
    return stripped.split("/")[-1] if stripped else ""


def _select_collection_entry(
    collections: list[dict[str, Any]],
    *,
    endpoint_url: str,
    collection_hint: str | None,
) -> dict[str, Any]:
    if len(collections) == 1:
        return collections[0]

    hint_tokens = _hint_tokens(collection_hint)
    if hint_tokens:
        exact_matches = [
            item
            for item in collections
            if _collection_identifier(item) and _collection_identifier(item) == hint_tokens
        ]
        if len(exact_matches) == 1:
            return exact_matches[0]

        fuzzy_matches = [
            item for item in collections if _collection_matches_hint(item, hint_tokens)
        ]
        if len(fuzzy_matches) == 1:
            return fuzzy_matches[0]

    raise ValueError(
        f"multiple collections advertised by {endpoint_url}; use a collection-specific URL or collection_hint"
    )


def _collection_matches_hint(collection_doc: dict[str, Any], hint_tokens: tuple[str, ...]) -> bool:
    candidate = _collection_identifier(collection_doc)
    if not candidate:
        return False
    candidate_set = set(candidate)
    hint_set = set(hint_tokens)
    return bool(candidate_set) and (
        candidate_set.issubset(hint_set) or hint_set.issubset(candidate_set)
    )


def _collection_identifier(collection_doc: dict[str, Any]) -> tuple[str, ...]:
    for key in ("id", "title", "description", "name"):
        value = collection_doc.get(key)
        tokens = _hint_tokens(value)
        if tokens:
            return tokens
    return ()


def _hint_tokens(value: Any) -> tuple[str, ...]:
    text = str(value or "").strip().lower()
    if not text:
        return ()
    tokens: list[str] = []
    current: list[str] = []
    for char in text:
        if char.isalnum():
            current.append(char)
            continue
        if current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    normalized = tuple(_normalize_token(token) for token in tokens if _normalize_token(token))
    return normalized


def _normalize_token(token: str) -> str:
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def _field_names(collection_doc: dict[str, Any]) -> tuple[str, ...]:
    item_assets = collection_doc.get("item_assets")
    if isinstance(item_assets, dict):
        return tuple(str(key) for key in item_assets.keys())
    summaries = collection_doc.get("summaries")
    if isinstance(summaries, dict):
        return tuple(str(key) for key in summaries.keys())
    return ()


def _next_link(payload: dict[str, Any], *, base_url: str) -> str | None:
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
