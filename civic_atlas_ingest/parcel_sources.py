"""Public parcel source helpers for Phase C envelope batches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .zoning_sources import (
    FLINT_PARCEL_GEOMETRY_LAYER_URL,
    HTTP_HEADERS,
    PARCEL_GEOMETRY_FIELDS,
    build_arcgis_query_url,
)


@dataclass(frozen=True)
class ParcelEnvelopeInput:
    parcel_key: str
    zoning_code: str
    geometry: dict[str, object]
    pid_dash: str | None = None
    land_use: str | None = None
    source_fid: int | str | None = None


def flint_parcel_query_url(*, limit: int, offset: int = 0) -> str:
    return build_arcgis_query_url(
        FLINT_PARCEL_GEOMETRY_LAYER_URL,
        {
            "where": "PIDdash IS NOT NULL AND Zoning IS NOT NULL",
            "outFields": ",".join(PARCEL_GEOMETRY_FIELDS),
            "returnGeometry": "true",
            "outSR": 4326,
            "resultRecordCount": limit,
            "resultOffset": offset,
            "f": "geojson",
        },
    )


def fetch_flint_zoned_parcels(
    *,
    limit: int | None = None,
    page_size: int = 500,
    timeout_s: float = 30.0,
) -> tuple[ParcelEnvelopeInput, ...]:
    """Fetch current Flint parcel geometries with public zoning attributes."""
    rows: list[ParcelEnvelopeInput] = []
    seen_keys: set[str] = set()
    offset = 0
    with httpx.Client(timeout=timeout_s, follow_redirects=True, headers=HTTP_HEADERS) as client:
        while True:
            requested = page_size if limit is None else min(page_size, limit - len(rows))
            if requested <= 0:
                break
            payload = _fetch_json(client, flint_parcel_query_url(limit=requested, offset=offset))
            page_rows = parcel_inputs_from_geojson(payload)
            new_rows = [row for row in page_rows if row.parcel_key not in seen_keys]
            if not new_rows:
                break
            for row in new_rows:
                seen_keys.add(row.parcel_key)
            rows.extend(new_rows)
            if limit is not None and len(rows) >= limit:
                return tuple(rows[:limit])
            if len(page_rows) < requested:
                break
            offset += requested
    return tuple(rows)


def parcel_inputs_from_geojson(payload: dict[str, Any]) -> tuple[ParcelEnvelopeInput, ...]:
    rows: list[ParcelEnvelopeInput] = []
    for feature in payload.get("features", []):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            continue
        zoning_code = _optional_text(properties.get("Zoning"))
        pid_dash = _optional_text(properties.get("PIDdash"))
        if zoning_code is None or pid_dash is None:
            continue
        rows.append(
            ParcelEnvelopeInput(
                parcel_key=pid_dash,
                pid_dash=pid_dash,
                zoning_code=zoning_code,
                land_use=_optional_text(properties.get("LandUse")),
                source_fid=properties.get("FID"),
                geometry=geometry,
            )
        )
    return tuple(rows)


def _fetch_json(client: httpx.Client, url: str) -> dict[str, Any]:
    response = client.get(url)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON from {url}")
    return payload


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
