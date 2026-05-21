"""Ray task: ingest Sanborn fire insurance map sheets via Mapwarper.

Status: skeleton. Real implementation is pending finalization of
the BuildingPresence / ArtifactAnchor proto and a Sanborn color-key
decoder (see docs/sanborn-key.md, TODO).

Mapwarper hosts georeferenced Sanborn sheets contributed by NYPL,
LOC, and others. For each sheet:

  1. Fetch the georeferenced TIFF + the warp metadata.
  2. Vectorize buildings via a Sanborn-color decoder. Sanborn uses
     a known color key: yellow=wood frame, pink/red=brick, blue=stone,
     gray=iron, brown=adobe. Story counts are printed in each polygon.
  3. OCR the story count digits in each polygon. Confidence is low,
     so coverage_quality is held to PRIMARY_ARCHIVAL ceiling.
  4. Emit per-sheet GeoJSON to a RunPod-mounted volume or object-store prefix
     for human spot-check.
  5. With `--commit-to-postgis`, write BuildingPresence +
     ArtifactAnchor records under tenant_id='corpus' for each
     vectorized polygon.

Run:
    ray job submit --working-dir . -- python -m civic_atlas_ingest.ingest_sanborn 12345

Environment:
    MAPWARPER_BASE_URL          override Mapwarper instance (default mapwarper.net)
    CIVIC_ATLAS_GRPC_URL        URL of the Atlas backend
    CIVIC_ATLAS_CORPUS_TOKEN    bearer token for the corpus tenant
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .coverage_quality import ProvenanceLane
from .runtime import ensure_ray_initialized, ray
from .training_corpus import bbox_polygon, make_training_record, write_training_batch

DEFAULT_MAPWARPER_BASE = "https://mapwarper.net"


@ray.remote(num_cpus=4, memory=8 * 1024 * 1024 * 1024)
def ingest_sheet(
    sheet_id: int,
    *,
    output_uri: str | None = None,
    fixture_json: str | None = None,
    dry_run: bool = True,
    commit_to_postgis: bool = False,
) -> dict[str, Any]:
    """Pull a single Sanborn sheet, vectorize buildings, optionally commit.

    `dry_run` writes only the spot-check GeoJSON to the attached volume.
    `commit_to_postgis` requires a moderator's eye on the spot-check
    output first.

    Returns { 'sheet_id', 'polygons', 'mean_coverage_quality',
              'spotcheck_path', 'records_emitted', 'records_written' }.
    """
    if dry_run and commit_to_postgis:
        raise ValueError("cannot dry_run AND commit_to_postgis simultaneously")
    metadata = _load_fixture_or_fetch_map(sheet_id, fixture_json)
    records = _records_from_sheet_metadata(metadata, sheet_id=sheet_id)
    batch = write_training_batch(records, source="sanborn", output_uri=output_uri)
    mean_quality = (
        sum(record.coverage.quality for record in records) / len(records) if records else 0.0
    )
    return {
        "sheet_id": sheet_id,
        "polygons": len(records),
        "mean_coverage_quality": round(mean_quality, 4),
        "spotcheck_path": str(batch.local_dir),
        "records_emitted": len(records),
        "records_written": 0,
        "commit_to_postgis": commit_to_postgis,
        "postgis_status": "not-wired",
        "review_required": True,
        "batch": batch.to_json(),
    }


@ray.remote(num_cpus=2, memory=4 * 1024 * 1024 * 1024)
def list_sheets_for_bbox(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
) -> list[int]:
    """List Mapwarper sheet IDs that intersect a bbox.

    Mapwarper offers a search endpoint that returns georeferenced
    sheets by bounding box. This wraps that endpoint and returns
    the sheet IDs for use with `ingest_sheet`.
    """
    base = os.environ.get("MAPWARPER_BASE_URL", DEFAULT_MAPWARPER_BASE).rstrip("/")
    params = {
        "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "format": "json",
        "rectified": "true",
    }

    import httpx

    response = httpx.get(f"{base}/maps.json", params=params, timeout=45, follow_redirects=True)
    response.raise_for_status()
    payload = response.json()
    return _sheet_ids_from_search_payload(payload)


def _records_from_sheet_metadata(
    metadata: dict[str, Any],
    *,
    sheet_id: int,
) -> list[Any]:
    geometry = _geometry_from_metadata(metadata)
    fields = {
        "display_name": (
            metadata.get("title") or metadata.get("name") or f"Sanborn sheet {sheet_id}"
        ),
        "start_date_raw": (
            metadata.get("year") or metadata.get("date") or metadata.get("created_at")
        ),
        "primary_material": "primary_archival_map",
        "building": "yes",
    }
    lanes = {
        "display_name": ProvenanceLane.PRIMARY_ARCHIVAL,
        "start_date_raw": ProvenanceLane.PRIMARY_ARCHIVAL,
        "primary_material": ProvenanceLane.PRIMARY_ARCHIVAL,
        "building": ProvenanceLane.PRIMARY_ARCHIVAL,
    }
    return [
        make_training_record(
            source="sanborn",
            source_id=f"mapwarper:{sheet_id}",
            city="flint",
            geometry=geometry,
            fields=fields,
            lanes=lanes,
            source_uri=f"{_MAPWARPER_BASE}/maps/{sheet_id}",
            extra={
                "mapwarper_metadata": metadata,
                "vectorization_status": "sheet-anchor-only",
                "review_required": True,
            },
        )
    ]


def _geometry_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    geojson = metadata.get("geojson") or metadata.get("geometry")
    if isinstance(geojson, str):
        try:
            geojson = json.loads(geojson)
        except json.JSONDecodeError:
            geojson = None
    if isinstance(geojson, dict) and geojson.get("type"):
        return geojson

    bbox = metadata.get("bbox") or metadata.get("bounds") or metadata.get("extent")
    if isinstance(bbox, str):
        bbox = [float(part.strip()) for part in bbox.split(",")]
    if isinstance(bbox, list) and len(bbox) == 4:
        west, south, east, north = [float(value) for value in bbox]
        return bbox_polygon(south, west, north, east)

    return bbox_polygon(42.952, -83.807, 43.092, -83.620)


def _sheet_ids_from_search_payload(payload: Any) -> list[int]:
    if isinstance(payload, dict):
        candidates = payload.get("items") or payload.get("maps") or payload.get("results") or []
    elif isinstance(payload, list):
        candidates = payload
    else:
        candidates = []
    ids: list[int] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id") or item.get("map_id")
        try:
            ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue
    return ids


def _load_fixture_or_fetch_map(sheet_id: int, fixture_json: str | None) -> dict[str, Any]:
    if fixture_json:
        value = _read_arg_or_path(fixture_json)
        return json.loads(value)

    import httpx

    response = httpx.get(
        f"{_MAPWARPER_BASE}/maps/{sheet_id}.json",
        timeout=45,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.json()


def _read_arg_or_path(value: str) -> str:
    if value.startswith("@"):
        return open(value[1:], encoding="utf-8").read()
    if os.path.exists(os.path.expanduser(value)):
        return open(os.path.expanduser(value), encoding="utf-8").read()
    return value


def main(argv: list[str] | None = None) -> None:
    """Local entrypoint for `ray job submit` or direct local smoke runs."""
    parser = argparse.ArgumentParser(description="Ingest a Mapwarper Sanborn sheet")
    parser.add_argument("sheet_id", nargs="?", type=int, default=0)
    parser.add_argument("--output-uri", default=None)
    parser.add_argument("--fixture-json", default=None)
    parser.add_argument("--commit-to-postgis", action="store_true")
    args = parser.parse_args(argv)

    if args.sheet_id == 0:
        print("Pass --sheet-id <id>. Use list_sheets_for_bbox to discover IDs.")
        return
    ensure_ray_initialized()
    result = ray.get(
        ingest_sheet.remote(
            sheet_id=args.sheet_id,
            output_uri=args.output_uri,
            fixture_json=args.fixture_json,
            dry_run=not args.commit_to_postgis,
            commit_to_postgis=args.commit_to_postgis,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))


_MAPWARPER_BASE = os.environ.get("MAPWARPER_BASE_URL", DEFAULT_MAPWARPER_BASE)


if __name__ == "__main__":
    main(sys.argv[1:])
