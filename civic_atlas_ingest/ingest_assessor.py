"""Ray task: ingest per-city assessor parcel records.

Status: skeleton. Each city has its own assessor data format and
publication channel. The plan is one Ray task per city,
all dispatched from `ingest_city(city_slug)`.

For each city with `assessor_public=True`:

  1. Download the latest assessor parcel layer (GeoJSON, shapefile,
     or REST). Source URLs live per-city in `_ASSESSOR_SOURCES`.
  2. Normalize columns to a stable field set: parcel_id, address,
     year_built, square_footage, primary_material, stories, owner.
  3. Spatial-join parcels to OSM building footprints already in the
     corpus tenant (call into the Atlas backend's GetNearbyArtifacts).
  4. For matched footprints, merge in assessor fields with
     AUTHORITATIVE_RECENT or AUTHORITATIVE_HISTORICAL lane depending
     on assessment date.
  5. Write back via UpdateBuildingPresence (a stub endpoint, see
     coordination note phase-4-reconstruction-spec-requirements.md
     for the dependency).

For cities with `assessor_public=False`, this app skips silently.
The corpus still receives OSM + Sanborn coverage but no assessor lift.

Run:
    ray job submit --working-dir . -- python -m civic_atlas_ingest.ingest_assessor detroit

Environment:
    CIVIC_ATLAS_GRPC_URL        URL of the Atlas backend
    CIVIC_ATLAS_CORPUS_TOKEN    bearer token for the corpus tenant
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any

from .artifact_persistence import persist_gis_artifacts
from .city_targets import CITY_TARGETS, get_target
from .coverage_quality import ProvenanceLane
from .gis_adapters import arcgis_rest, ogc_api_features, stac, wfs
from .runtime import ensure_ray_initialized, ray
from .training_corpus import make_training_record, write_training_batch
from .zoning_sources import FLINT_PARCEL_GEOMETRY_LAYER_URL

# Per-city assessor source URLs. Each entry is either a single URL
# (GeoJSON/CSV) or a REST endpoint base + layer config. Empty list
# means the city's assessor data is not publicly retrievable.
_ASSESSOR_SOURCES: dict[str, list[str]] = {
    "flint": [FLINT_PARCEL_GEOMETRY_LAYER_URL],
    "detroit": ["https://data.detroitmi.gov/api/.../parcels"],
    "buffalo": ["https://data.buffalony.gov/api/.../parcels"],
    "cleveland": ["https://data.cuyahogacounty.us/.../assessor"],
    "pittsburgh": ["https://data.alleghenycounty.us/.../parcels"],
    "toledo": ["https://data.lucascountyoh.gov/.../parcels"],
    "akron": ["https://data.summitoh.net/.../parcels"],
    "milwaukee": ["https://data.milwaukee.gov/.../parcels"],
    "saginaw": [],
    "bay-city": [],
    "youngstown": ["https://data.mahoningcountyoh.gov/.../parcels"],
}


@ray.remote(num_cpus=4, memory=8 * 1024 * 1024 * 1024)
def ingest_city(
    city: str,
    *,
    output_uri: str | None = None,
    fixture_json: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Ingest one city's assessor records.

    For cities where `assessor_public=False`, returns immediately
    with `{ 'skipped': True, 'reason': 'no public source' }`.
    """
    target = get_target(city)
    if not target.assessor_public:
        return {"city": city, "skipped": True, "reason": "no public source"}

    sources = _ASSESSOR_SOURCES.get(city, [])
    if not sources:
        return {"city": city, "skipped": True, "reason": "source URL not configured"}

    return ingest_from_discovered_endpoint(
        sources[0],
        source_class=_source_class_for_url(sources[0]),
        city=target.slug,
        output_uri=output_uri,
        fixture_json=fixture_json,
        limit=limit,
    )


@ray.remote(num_cpus=1)
def status() -> dict[str, list[str]]:
    """Return the configured-vs-skipped breakdown across all targets."""
    configured = [t.slug for t in CITY_TARGETS if _ASSESSOR_SOURCES.get(t.slug)]
    skipped = [t.slug for t in CITY_TARGETS if not _ASSESSOR_SOURCES.get(t.slug)]
    return {"configured": configured, "skipped": skipped}


def ingest_from_discovered_endpoint(
    endpoint_url: str,
    *,
    source_class: str,
    city: str,
    output_uri: str | None = None,
    fixture_json: str | None = None,
    limit: int = 200,
    persist_artifacts: bool | None = None,
    tenant_id: str = "flint",
    collection_hint: str | None = None,
) -> dict[str, Any]:
    payload = _load_fixture_or_fetch_city(
        city,
        endpoint_url,
        fixture_json,
        source_class=source_class,
        limit=limit,
        collection_hint=collection_hint,
    )
    records = _records_from_assessor_payload(
        payload,
        city=city,
        source_uri=endpoint_url,
        limit=limit,
    )
    batch = write_training_batch(records, source="assessor", output_uri=output_uri)
    should_persist = persist_artifacts
    if should_persist is None:
        should_persist = bool(os.environ.get("CIVIC_ATLAS_GRPC_URL", "").strip())
    persisted_artifacts = (
        persist_gis_artifacts(
            records,
            source_class=source_class,
            source_uri=endpoint_url,
            capabilities=payload.get("capabilities"),
            city=city,
            tenant_id=tenant_id,
        )
        if should_persist
        else []
    )
    mean_quality = (
        sum(record.coverage.quality for record in records) / len(records) if records else 0.0
    )
    return {
        "city": city,
        "sources": [endpoint_url],
        "source_class": source_class,
        "records_written": len(records),
        "persisted_artifacts": len(persisted_artifacts),
        "mean_coverage_quality": round(mean_quality, 4),
        "batch": batch.to_json(),
        "capabilities": payload.get("capabilities"),
    }


def _load_fixture_or_fetch_city(
    city: str,
    source_url: str,
    fixture_json: str | None,
    *,
    source_class: str,
    limit: int,
    collection_hint: str | None,
) -> dict[str, Any]:
    if fixture_json:
        return json.loads(_read_arg_or_path(fixture_json))
    if source_class == "arcgis_rest":
        return _fetch_arcgis_feature_layer(source_url, limit=limit)
    if source_class == "ogc_api_features":
        return _fetch_ogc_api_features(source_url, limit=limit, collection_hint=collection_hint)
    if source_class == "wfs":
        return _fetch_wfs_feature_service(source_url, limit=limit)
    if source_class == "stac":
        return _fetch_stac_items(source_url, limit=limit)
    if source_class == "geojson":
        return _fetch_geojson_dump(source_url, limit=limit)
    if city == "flint" and "tiles.regrid.com" in source_url:
        return _fetch_regrid_tilejson_sample(source_url)
    if "..." in source_url:
        raise RuntimeError(f"assessor source URL is still a placeholder: {source_url}")
    raise RuntimeError(f"unsupported assessor source format: {source_url} ({source_class})")


def _fetch_arcgis_feature_layer(source_url: str, *, limit: int) -> dict[str, Any]:
    capabilities = arcgis_rest.read_capabilities(source_url)
    features = list(arcgis_rest.fetch_all_features(source_url, limit=limit))
    return {
        "kind": "arcgis_rest_feature_layer",
        "capabilities": capabilities.to_json(),
        "features": features,
    }


def _fetch_ogc_api_features(
    source_url: str,
    *,
    limit: int,
    collection_hint: str | None,
) -> dict[str, Any]:
    capabilities = ogc_api_features.read_capabilities(
        source_url,
        collection_hint=collection_hint,
    )
    features = list(
        ogc_api_features.fetch_all_features(
            source_url,
            limit=limit,
            collection_hint=collection_hint,
        )
    )
    return {
        "kind": "ogc_api_features_collection",
        "capabilities": capabilities.to_json(),
        "features": features,
    }


def _fetch_wfs_feature_service(source_url: str, *, limit: int) -> dict[str, Any]:
    capabilities = wfs.read_capabilities(source_url)
    features = list(wfs.fetch_all_features(source_url, limit=limit))
    return {
        "kind": "wfs_feature_service",
        "capabilities": capabilities.to_json(),
        "features": features,
    }


def _fetch_stac_items(source_url: str, *, limit: int) -> dict[str, Any]:
    capabilities = stac.read_capabilities(source_url)
    features = list(stac.fetch_all_features(source_url, limit=limit))
    return {
        "kind": "stac_item_collection",
        "capabilities": capabilities.to_json(),
        "features": features,
    }


def _fetch_geojson_dump(source_url: str, *, limit: int) -> dict[str, Any]:
    import httpx

    response = httpx.get(source_url, timeout=30, follow_redirects=True)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ValueError(f"expected GeoJSON FeatureCollection from {source_url}")
    return {
        "kind": "geojson_feature_collection",
        "capabilities": {
            "endpoint_url": source_url,
            "title": payload.get("name") or "GeoJSON FeatureCollection",
        },
        "features": payload.get("features", [])[:limit],
    }


def _fetch_regrid_tilejson_sample(source_url: str) -> dict[str, Any]:
    import httpx

    tilejson_response = httpx.get(source_url, timeout=20, follow_redirects=True)
    tilejson_response.raise_for_status()
    tilejson = tilejson_response.json()
    grid_template = tilejson["grids"][0]
    z, x, y = _lonlat_to_tile(lon=-83.692, lat=43.017, zoom=15)
    grid_url = grid_template.format(z=z, x=x, y=y)
    grid_response = httpx.get(grid_url, timeout=20, follow_redirects=True)
    grid_response.raise_for_status()
    return {"kind": "regrid_tilejson_sample", "tilejson": tilejson, "grid": grid_response.json()}


def _records_from_assessor_payload(
    payload: dict[str, Any],
    *,
    city: str,
    source_uri: str,
    limit: int,
) -> list[Any]:
    if "features" in payload:
        rows = [
            feature.get("properties", {}) | {"geojson": feature.get("geometry")}
            for feature in payload["features"]
        ]
    elif payload.get("kind") == "regrid_tilejson_sample":
        rows = list(payload.get("grid", {}).get("data", {}).values())
    elif payload.get("kind") == "arcgis_rest_feature_layer":
        rows = [
            feature.get("properties", {}) | {"geojson": feature.get("geometry")}
            for feature in payload.get("features", [])
            if isinstance(feature, dict)
        ]
    elif "data" in payload and isinstance(payload["data"], dict):
        rows = list(payload["data"].values())
    elif isinstance(payload.get("records"), list):
        rows = payload["records"]
    else:
        rows = []

    records = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        geometry = _geometry_from_row(row)
        if not geometry:
            continue
        fields = _fields_from_row(row)
        lanes = {key: ProvenanceLane.AUTHORITATIVE_RECENT for key in fields}
        records.append(
            make_training_record(
                source="assessor",
                source_id=str(
                    row.get("parcelnumb")
                    or row.get("parcel_id")
                    or row.get("PIDdash")
                    or row.get("PIDText")
                    or row.get("fid")
                ),
                city=city,
                geometry=geometry,
                fields=fields,
                lanes=lanes,
                source_uri=source_uri,
                extra={"assessor_row": _safe_row(row)},
            )
        )
    return records


def _fields_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "parcel_id": (
                row.get("parcelnumb")
                or row.get("parcel_id")
                or row.get("parcel")
                or row.get("PIDdash")
                or row.get("PIDText")
            ),
            "address": row.get("address") or row.get("site_address") or row.get("Full_Prop") or row.get("Prop_Add"),
            "year_built": row.get("year_built") or row.get("yr_built") or _int_like(row.get("Year_Built")),
            "square_footage": row.get("square_footage") or row.get("bldg_sqft"),
            "stories": (
                row.get("stories")
                or row.get("num_stories")
                or _int_like(row.get("Cib_Storie"))
                or _int_like(row.get("Dwelling_U"))
            ),
            "building": row.get("building") or row.get("use_type") or row.get("Use_Type") or row.get("LandUse") or "parcel",
            "use_type": row.get("use_type") or row.get("property_class") or row.get("Use_Type") or row.get("LandUse"),
            "property_class": row.get("property_class") or row.get("Prop_Class"),
            "primary_material": row.get("primary_material") or row.get("building_material") or row.get("material"),
        }.items()
        if value not in (None, "")
    }


def _geometry_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    geojson = row.get("geojson") or row.get("geometry")
    if isinstance(geojson, str):
        try:
            geojson = json.loads(geojson)
        except json.JSONDecodeError:
            return None
    if isinstance(geojson, dict) and geojson.get("type"):
        return geojson
    return None


def _safe_row(row: dict[str, Any]) -> dict[str, Any]:
    blocked = {"owner", "tx_payname", "tx_pay_add", "tx_paycity", "txpaystate", "tx_pay_zip", "tx_payctry"}
    return {key: value for key, value in row.items() if key.lower() not in blocked}


def _source_class_for_url(source_url: str) -> str:
    lowered = source_url.lower()
    if "/featureserver/" in lowered or "/mapserver/" in lowered:
        return "arcgis_rest"
    if "service=wfs" in lowered or lowered.endswith("/wfs") or "geoserver" in lowered:
        return "wfs"
    if "/stac" in lowered or lowered.rstrip("/").endswith("catalog.json"):
        return "stac"
    if "/collections" in lowered or "/items" in lowered or "api/features" in lowered:
        return "ogc_api_features"
    if lowered.endswith(".geojson"):
        return "geojson"
    if "tiles.regrid.com" in lowered:
        return "geojson"
    return "unknown"


def _int_like(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def _lonlat_to_tile(*, lon: float, lat: float, zoom: int) -> tuple[int, int, int]:
    lat_rad = math.radians(lat)
    n = 2.0**zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return zoom, x, y


def _read_arg_or_path(value: str) -> str:
    if value.startswith("@"):
        return open(value[1:], encoding="utf-8").read()
    if os.path.exists(os.path.expanduser(value)):
        return open(os.path.expanduser(value), encoding="utf-8").read()
    return value


def main(argv: list[str] | None = None) -> None:
    """Local entrypoint for `ray job submit` or direct local smoke runs."""
    parser = argparse.ArgumentParser(description="Ingest assessor parcel records")
    parser.add_argument("city", nargs="?", default="flint")
    parser.add_argument("--output-uri", default=None)
    parser.add_argument("--fixture-json", default=None)
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args(argv)

    ensure_ray_initialized()
    result = ray.get(
        ingest_city.remote(
            city=args.city,
            output_uri=args.output_uri,
            fixture_json=args.fixture_json,
            limit=args.limit,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1:])
