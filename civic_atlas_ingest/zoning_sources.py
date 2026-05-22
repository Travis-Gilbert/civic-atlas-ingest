"""Official zoning source snapshotting for Flint Phase C.

The source boundary is deliberately plain HTTP/JSON. ArcGIS REST endpoints are
used only as public municipal data services; no Esri SDK or proprietary runtime
is required by this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

HTTP_HEADERS = {"User-Agent": "civic-atlas-ingest/0.1 (+https://www.ouratlas.org)"}

FLINT_ZONING_PAGE_URL = "https://www.cityofflint.com/zoning-division/"
FLINT_ZONING_CODE_URL = (
    "https://www.cityofflint.com/wp-content/uploads/2024/01/"
    "2025-ZC-v1.5.1-Ord.-240459-T-Amendments-Minor-Corrections.pdf"
)
FLINT_ZONING_ARTICLE_8_URL = "https://www.cityofflint.com/wp-content/uploads/2023/03/Article-8.pdf"
FLINT_ZONING_MAP_PDF_URL = (
    "https://www.cityofflint.com/wp-content/uploads/2024/01/Zoning-Map_2.6.25.pdf"
)
FLINT_ZONING_USE_TABLE_URL = (
    "https://www.cityofflint.com/wp-content/uploads/2023/04/Comprehensive-Use-Table-3.5.26-1.pdf"
)
FLINT_ZONING_QUICK_REFERENCE_URL = (
    "https://www.cityofflint.com/wp-content/uploads/2022/04/"
    "Quick-Reference-Guide-May-17_-2016_City-Edits_RS.pdf"
)
FLINT_PARCEL_GEOMETRY_LAYER_URL = (
    "https://services5.arcgis.com/lqqWNtSxx8Akj04A/ArcGIS/rest/services/"
    "Main_COF_Parcel_view/FeatureServer/0"
)
FLINT_PARCEL_ZONING_TABLE_URL = (
    "https://services5.arcgis.com/lqqWNtSxx8Akj04A/ArcGIS/rest/services/"
    "COF_Parcel_Zoning_Viewtbl/FeatureServer/0"
)

PARCEL_GEOMETRY_FIELDS = ("FID", "PIDdash", "PIDText", "Zoning", "LandUse")
PARCEL_ZONING_FIELDS = (
    "FID2",
    "PIDdash",
    "Current_Zoning",
    "Current_Landuse",
    "Previous_Zoning",
    "Ward",
)


@dataclass(frozen=True)
class ZoningSourceRef:
    key: str
    label: str
    url: str
    kind: str
    required_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceSnapshot:
    key: str
    label: str
    url: str
    final_url: str
    kind: str
    status_code: int
    content_type: str
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class LayerProbe:
    key: str
    url: str
    query_url: str
    required_fields: tuple[str, ...]
    observed_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    max_record_count: int | None
    supports_pagination: bool


@dataclass(frozen=True)
class ParcelZoningJoinRow:
    pid_dash: str
    parcel_zoning: str | None
    table_zoning: str | None
    parcel_land_use: str | None
    table_land_use: str | None
    zoning_matches: bool
    land_use_matches: bool


@dataclass(frozen=True)
class ParcelZoningJoinProbe:
    parcel_query_url: str
    zoning_query_url: str
    sample_size: int
    joined_count: int
    missing_pid_count: int
    mismatched_count: int
    rows: tuple[ParcelZoningJoinRow, ...]


def flint_zoning_source_refs() -> tuple[ZoningSourceRef, ...]:
    """Return the public official Flint sources needed for Phase C."""
    return (
        ZoningSourceRef(
            key="flint-zoning-division-page",
            label="City of Flint Zoning Division page",
            url=FLINT_ZONING_PAGE_URL,
            kind="html",
        ),
        ZoningSourceRef(
            key="flint-zoning-code-2025-v1-5-1",
            label="City of Flint Zoning Code v1.5.1",
            url=FLINT_ZONING_CODE_URL,
            kind="pdf",
        ),
        ZoningSourceRef(
            key="flint-zoning-article-8",
            label="City of Flint zoning Article 8",
            url=FLINT_ZONING_ARTICLE_8_URL,
            kind="pdf",
        ),
        ZoningSourceRef(
            key="flint-zoning-map-2025-02-06",
            label="City of Flint zoning map dated 2025-02-06",
            url=FLINT_ZONING_MAP_PDF_URL,
            kind="pdf",
        ),
        ZoningSourceRef(
            key="flint-comprehensive-use-table-2026-03-05",
            label="City of Flint comprehensive use table dated 2026-03-05",
            url=FLINT_ZONING_USE_TABLE_URL,
            kind="pdf",
        ),
        ZoningSourceRef(
            key="flint-zoning-quick-reference",
            label="City of Flint zoning quick reference guide",
            url=FLINT_ZONING_QUICK_REFERENCE_URL,
            kind="pdf",
        ),
        ZoningSourceRef(
            key="flint-parcel-geometry-layer",
            label="City of Flint parcel geometry layer metadata",
            url=f"{FLINT_PARCEL_GEOMETRY_LAYER_URL}?f=pjson",
            kind="arcgis-rest-metadata",
            required_fields=PARCEL_GEOMETRY_FIELDS,
        ),
        ZoningSourceRef(
            key="flint-parcel-zoning-table",
            label="City of Flint parcel zoning table metadata",
            url=f"{FLINT_PARCEL_ZONING_TABLE_URL}?f=pjson",
            kind="arcgis-rest-metadata",
            required_fields=PARCEL_ZONING_FIELDS,
        ),
    )


def build_arcgis_query_url(base_url: str, params: dict[str, str | int | bool]) -> str:
    """Build a stable ArcGIS REST query URL for manifests and debugging."""
    encoded = urlencode({key: _arcgis_param_value(value) for key, value in params.items()})
    return f"{base_url}/query?{encoded}"


def layer_probe_from_metadata(
    *,
    key: str,
    url: str,
    query_url: str,
    metadata: dict[str, Any],
    required_fields: tuple[str, ...],
) -> LayerProbe:
    all_observed_fields = tuple(
        field["name"]
        for field in metadata.get("fields", [])
        if isinstance(field, dict) and isinstance(field.get("name"), str)
    )
    observed = set(all_observed_fields)
    observed_required_fields = tuple(field for field in required_fields if field in observed)
    missing = tuple(field for field in required_fields if field not in observed)
    supports_pagination = bool(
        metadata.get("advancedQueryCapabilities", {}).get("supportsPagination", False)
    )
    max_record_count_raw = metadata.get("maxRecordCount")
    max_record_count = max_record_count_raw if isinstance(max_record_count_raw, int) else None
    return LayerProbe(
        key=key,
        url=url,
        query_url=query_url,
        required_fields=required_fields,
        observed_fields=observed_required_fields,
        missing_fields=missing,
        max_record_count=max_record_count,
        supports_pagination=supports_pagination,
    )


def parcel_geometry_query_url(sample_size: int) -> str:
    return build_arcgis_query_url(
        FLINT_PARCEL_GEOMETRY_LAYER_URL,
        {
            "where": "PIDdash IS NOT NULL",
            "outFields": ",".join(PARCEL_GEOMETRY_FIELDS),
            "returnGeometry": "true",
            "outSR": 4326,
            "resultRecordCount": sample_size,
            "f": "geojson",
        },
    )


def parcel_zoning_query_url(pid_dashes: tuple[str, ...]) -> str:
    where = "1=0"
    if pid_dashes:
        quoted = ",".join(f"'{pid}'" for pid in pid_dashes)
        where = f"PIDdash in ({quoted})"
    return build_arcgis_query_url(
        FLINT_PARCEL_ZONING_TABLE_URL,
        {
            "where": where,
            "outFields": ",".join(PARCEL_ZONING_FIELDS),
            "returnGeometry": "false",
            "resultRecordCount": max(len(pid_dashes), 1),
            "f": "json",
        },
    )


def parcel_zoning_join_probe_from_payloads(
    *,
    parcel_query_url: str,
    zoning_query_url: str,
    parcel_payload: dict[str, Any],
    zoning_payload: dict[str, Any],
) -> ParcelZoningJoinProbe:
    parcel_features = [
        feature
        for feature in parcel_payload.get("features", [])
        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict)
    ]
    table_features = [
        feature
        for feature in zoning_payload.get("features", [])
        if isinstance(feature, dict) and isinstance(feature.get("attributes"), dict)
    ]
    zoning_by_pid = {
        str(feature["attributes"]["PIDdash"]): feature["attributes"]
        for feature in table_features
        if feature["attributes"].get("PIDdash")
    }
    rows: list[ParcelZoningJoinRow] = []
    missing_pid_count = 0

    for feature in parcel_features:
        props = feature["properties"]
        pid_dash = str(props.get("PIDdash") or "")
        if not pid_dash:
            missing_pid_count += 1
            continue
        zoning = zoning_by_pid.get(pid_dash)
        parcel_zoning = _optional_string(props.get("Zoning"))
        table_zoning = _optional_string(zoning.get("Current_Zoning")) if zoning else None
        parcel_land_use = _optional_string(props.get("LandUse"))
        table_land_use = _optional_string(zoning.get("Current_Landuse")) if zoning else None
        rows.append(
            ParcelZoningJoinRow(
                pid_dash=pid_dash,
                parcel_zoning=parcel_zoning,
                table_zoning=table_zoning,
                parcel_land_use=parcel_land_use,
                table_land_use=table_land_use,
                zoning_matches=parcel_zoning == table_zoning,
                land_use_matches=parcel_land_use == table_land_use,
            )
        )

    mismatched_count = sum(1 for row in rows if not row.zoning_matches or not row.land_use_matches)
    return ParcelZoningJoinProbe(
        parcel_query_url=parcel_query_url,
        zoning_query_url=zoning_query_url,
        sample_size=len(parcel_features),
        joined_count=len(rows),
        missing_pid_count=missing_pid_count,
        mismatched_count=mismatched_count,
        rows=tuple(rows),
    )


def build_flint_zoning_source_snapshot(
    *,
    sample_size: int = 5,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Fetch current Flint source metadata and return a reproducible manifest."""
    retrieved_at = datetime.now(UTC).isoformat()
    with httpx.Client(timeout=timeout_s, follow_redirects=True, headers=HTTP_HEADERS) as client:
        source_snapshots = [_snapshot_ref(client, ref) for ref in flint_zoning_source_refs()]
        parcel_metadata = _fetch_json(client, f"{FLINT_PARCEL_GEOMETRY_LAYER_URL}?f=pjson")
        zoning_metadata = _fetch_json(client, f"{FLINT_PARCEL_ZONING_TABLE_URL}?f=pjson")

        parcel_probe_url = parcel_geometry_query_url(sample_size)
        parcel_payload = _fetch_json(client, parcel_probe_url)
        pid_dashes = _pid_dashes_from_parcel_payload(parcel_payload)
        zoning_probe_url = parcel_zoning_query_url(pid_dashes)
        zoning_payload = _fetch_json(client, zoning_probe_url)

    layer_probes = (
        layer_probe_from_metadata(
            key="flint-parcel-geometry-layer",
            url=FLINT_PARCEL_GEOMETRY_LAYER_URL,
            query_url=parcel_probe_url,
            metadata=parcel_metadata,
            required_fields=PARCEL_GEOMETRY_FIELDS,
        ),
        layer_probe_from_metadata(
            key="flint-parcel-zoning-table",
            url=FLINT_PARCEL_ZONING_TABLE_URL,
            query_url=zoning_probe_url,
            metadata=zoning_metadata,
            required_fields=PARCEL_ZONING_FIELDS,
        ),
    )
    join_probe = parcel_zoning_join_probe_from_payloads(
        parcel_query_url=parcel_probe_url,
        zoning_query_url=zoning_probe_url,
        parcel_payload=parcel_payload,
        zoning_payload=zoning_payload,
    )

    return {
        "city": "flint",
        "phase": "phase-c-zoning-envelope",
        "retrieved_at": retrieved_at,
        "esri_dependency_policy": (
            "ArcGIS REST endpoints are treated as public municipal HTTP/JSON sources only; "
            "OpenAtlas does not require Esri SDKs, ArcGIS Urban, CityEngine, or ArcGIS Runtime."
        ),
        "source_snapshots": [asdict(snapshot) for snapshot in source_snapshots],
        "layer_probes": [asdict(probe) for probe in layer_probes],
        "join_probe": asdict(join_probe),
    }


def write_flint_zoning_source_snapshot(
    output_path: Path,
    *,
    sample_size: int = 5,
) -> dict[str, Any]:
    manifest = build_flint_zoning_source_snapshot(sample_size=sample_size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _snapshot_ref(client: httpx.Client, ref: ZoningSourceRef) -> SourceSnapshot:
    response = client.get(ref.url)
    response.raise_for_status()
    body = response.content
    return SourceSnapshot(
        key=ref.key,
        label=ref.label,
        url=ref.url,
        final_url=str(response.url),
        kind=ref.kind,
        status_code=response.status_code,
        content_type=response.headers.get("content-type", ""),
        byte_count=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
    )


def _fetch_json(client: httpx.Client, url: str) -> dict[str, Any]:
    response = client.get(url)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON from {url}")
    return payload


def _pid_dashes_from_parcel_payload(payload: dict[str, Any]) -> tuple[str, ...]:
    pids: list[str] = []
    for feature in payload.get("features", []):
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties")
        if not isinstance(props, dict):
            continue
        pid_dash = props.get("PIDdash")
        if pid_dash:
            pids.append(str(pid_dash))
    return tuple(pids)


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _arcgis_param_value(value: str | int | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Snapshot Flint zoning sources for Phase C.")
    parser.add_argument(
        "--output",
        default="city_packs/flint/zoning/source-manifest.json",
        help="Manifest path to write.",
    )
    parser.add_argument("--sample-size", type=int, default=5)
    args = parser.parse_args(argv)

    manifest = write_flint_zoning_source_snapshot(Path(args.output), sample_size=args.sample_size)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1:])
