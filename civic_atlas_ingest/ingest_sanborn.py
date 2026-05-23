"""Ray tasks: ingest Sanborn fire insurance map sheets.

Two code paths:

  - `ingest_sheet`: pull a sheet from Mapwarper by ID, emit ONE
    sheet-anchor record. Older path, still useful for sheets only
    available on Mapwarper.

  - `ingest_local_sheet`: ingest a locally-held Sanborn raster
    (LoC public-domain TIFFs, UM-Flint GIS Center scans, project-
    owner private holdings). Runs the full color-decode →
    vectorize → georef → per-polygon TrainingCorpusRecord pipeline.
    THIS is the path that populates DecodedArtifact rows at scale.

Sanborn color key (encoded by `sanborn_color_decoder.DEFAULT_BANDS`):

    yellow → wood frame   pink/red → brick   blue → stone
    gray   → iron/steel   brown    → adobe   olive → special combustible
    black  → labels / lot lines    white    → paper background

Story counts are printed digits inside each polygon. The vectorizer
calls `sanborn_vectorize.extract_story_count` (Tesseract-backed,
graceful fallback when missing).

Run:
    # Mapwarper path:
    ray job submit --working-dir . -- python -m civic_atlas_ingest.ingest_sanborn 12345

    # Local sheet path:
    ray job submit --working-dir . -- python -m civic_atlas_ingest.ingest_sanborn \\
        --local-georef path/to/flint-1925-03.georef.json

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
from pathlib import Path
from typing import Any

from .coverage_quality import ProvenanceLane
from .runtime import ensure_ray_initialized, ray
from .training_corpus import (
    TrainingCorpusRecord,
    bbox_polygon,
    make_training_record,
    write_training_batch,
)

DEFAULT_MAPWARPER_BASE = "https://mapwarper.net"

# Map MaterialCode integer → field-friendly material string.
# Keys are written as strings so the module imports without forcing
# the color-decoder module load at import time (it pulls numpy).
_MATERIAL_NAME_BY_CODE: dict[int, str] = {
    1: "wood_frame",
    2: "brick",
    3: "stone",
    4: "iron",
    5: "adobe",
    6: "special_combustible",
}


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


def _ingest_local_sheet_impl(
    georef_json: str,
    *,
    output_uri: str | None = None,
    dry_run: bool = True,
    commit_to_postgis: bool = False,
    enable_ocr: bool = True,
    city: str = "flint",
) -> dict[str, Any]:
    """Pure-function body of `ingest_local_sheet`. Split out from the
    Ray-decorated function so tests can call this directly without
    `ray.init()`.

    Pipeline:
      1. Load the georeferencing JSON (sheet_id, year, source, and
         pixel-to-geo transform via bbox or control points).
      2. Read the raster (TIFF/PNG/JPEG) via PIL.
      3. HSV-classify pixels by Sanborn material (color decoder).
      4. Vectorize same-material connected components into polygons.
      5. For each polygon: extract story count via OCR (best-effort),
         transform pixel polygon → lat/lng polygon via affine.
      6. Emit one TrainingCorpusRecord per polygon, all tagged
         ProvenanceLane.PRIMARY_ARCHIVAL.
      7. Write the batch via training_corpus.write_training_batch.

    `georef_json`: path to a sheet-georef JSON (or the JSON string
    itself, when called directly). See `sanborn_georef` for the
    shape spec.

    Returns metrics + the batch result. `dry_run=True` writes only
    the local spot-check files; `commit_to_postgis=True` requires
    PostGIS commit wiring (currently `not-wired` — see the audit
    doc for the gating ArtifactAnchor proto work).
    """
    if dry_run and commit_to_postgis:
        raise ValueError("cannot dry_run AND commit_to_postgis simultaneously")

    # Local imports so the Mapwarper path doesn't pay the numpy /
    # PIL / rasterio import cost when it isn't used.
    import numpy as np
    from PIL import Image

    from .sanborn_color_decoder import classify_pixels, classification_summary
    from .sanborn_georef import load_georeference, parse_georeference, transform_polygon
    from .sanborn_vectorize import (
        extract_polygons,
        extract_story_count,
        iter_polygon_regions,
    )

    # Accept either a path to a JSON file or the JSON content
    # directly (the @-prefix convention from training_corpus is
    # already supported by _read_arg_or_path).
    if Path(georef_json).exists():
        georef = load_georeference(Path(georef_json))
    else:
        payload = json.loads(_read_arg_or_path(georef_json))
        georef = parse_georeference(payload, base_dir=Path.cwd())

    # Load the raster as a uint8 RGB array. Pillow handles TIFF,
    # PNG, and JPEG; rasterio could read GeoTIFFs more efficiently
    # but Sanborn scans are typically plain RGB rasters.
    with Image.open(georef.image_path) as image:
        if image.mode != "RGB":
            image = image.convert("RGB")
        rgb = np.array(image)

    # Color-decode the entire raster.
    classified = classify_pixels(rgb)
    summary = classification_summary(classified)

    # Vectorize the material-classified raster into polygons.
    polygon_records = extract_polygons(classified)

    # Build one TrainingCorpusRecord per polygon.
    records: list[TrainingCorpusRecord] = []
    polygon_iter = iter_polygon_regions(rgb, polygon_records) if enable_ocr else iter(())
    if enable_ocr:
        story_count_by_index: dict[int, int | None] = {}
        for poly_record, patch in polygon_iter:
            idx = polygon_records.index(poly_record)
            story_count_by_index[idx] = extract_story_count(patch)
    else:
        story_count_by_index = {}

    sheet_year = georef.year
    sheet_id = georef.sheet_id
    sheet_source = georef.source

    for idx, poly_record in enumerate(polygon_records):
        material_name = _MATERIAL_NAME_BY_CODE.get(int(poly_record.material), "unknown")
        story_count = story_count_by_index.get(idx)
        geo_polygon = transform_polygon(poly_record.polygon_pixel, georef)

        fields: dict[str, Any] = {
            "building": "yes",
            "primary_material": material_name,
            "start_date_raw": str(sheet_year),
            "display_name": f"Sanborn polygon {sheet_id}:{idx}",
        }
        if story_count is not None:
            fields["stories"] = story_count

        lanes: dict[str, ProvenanceLane | list[ProvenanceLane]] = {
            "building": ProvenanceLane.PRIMARY_ARCHIVAL,
            "primary_material": ProvenanceLane.PRIMARY_ARCHIVAL,
            "start_date_raw": ProvenanceLane.PRIMARY_ARCHIVAL,
            "display_name": ProvenanceLane.PRIMARY_ARCHIVAL,
        }
        if story_count is not None:
            lanes["stories"] = ProvenanceLane.PRIMARY_ARCHIVAL

        records.append(
            make_training_record(
                source="sanborn",
                source_id=f"{sheet_id}:polygon:{idx}",
                city=city,
                geometry=geo_polygon,
                fields=fields,
                lanes=lanes,
                source_uri=georef.source_uri,
                extra={
                    "sheet_id": sheet_id,
                    "sheet_year": sheet_year,
                    "sheet_source": sheet_source,
                    "material_code": int(poly_record.material),
                    "area_pixels": poly_record.area_pixels,
                    "bbox_pixel": list(poly_record.bbox_pixel),
                    "polygon_index_in_sheet": idx,
                    "ocr_attempted": enable_ocr,
                    "vectorization_status": "per_polygon",
                    "review_required": True,
                },
            )
        )

    batch = write_training_batch(records, source="sanborn", output_uri=output_uri)
    mean_quality = (
        sum(r.coverage.quality for r in records) / len(records) if records else 0.0
    )
    return {
        "sheet_id": sheet_id,
        "sheet_year": sheet_year,
        "image_path": str(georef.image_path),
        "image_dims": [georef.image_width, georef.image_height],
        "polygons": len(records),
        "mean_coverage_quality": round(mean_quality, 4),
        "color_classification_summary": summary,
        "spotcheck_path": str(batch.local_dir),
        "records_emitted": len(records),
        "records_written": 0,
        "commit_to_postgis": commit_to_postgis,
        "postgis_status": "not-wired",
        "review_required": True,
        "batch": batch.to_json(),
    }


@ray.remote(num_cpus=4, memory=8 * 1024 * 1024 * 1024)
def ingest_local_sheet(
    georef_json: str,
    *,
    output_uri: str | None = None,
    dry_run: bool = True,
    commit_to_postgis: bool = False,
    enable_ocr: bool = True,
    city: str = "flint",
) -> dict[str, Any]:
    """Ray-decorated wrapper around `_ingest_local_sheet_impl`.

    The actual logic lives in the implementation function for testability;
    this wrapper exists so callers can do `ingest_local_sheet.remote(...)`
    against a Ray cluster.
    """
    return _ingest_local_sheet_impl(
        georef_json=georef_json,
        output_uri=output_uri,
        dry_run=dry_run,
        commit_to_postgis=commit_to_postgis,
        enable_ocr=enable_ocr,
        city=city,
    )


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
    """Local entrypoint for `ray job submit` or direct local smoke runs.

    Two routes:
      - Pass a positional `sheet_id` (Mapwarper integer) to use the
        Mapwarper fetch path. Emits one sheet-anchor record.
      - Pass `--local-georef path/to/sheet.georef.json` to run the
        full local color-decode + vectorize + per-polygon ingest.
    """
    parser = argparse.ArgumentParser(description="Ingest a Sanborn sheet")
    parser.add_argument("sheet_id", nargs="?", type=int, default=0)
    parser.add_argument("--output-uri", default=None)
    parser.add_argument("--fixture-json", default=None)
    parser.add_argument(
        "--local-georef",
        default=None,
        help="Path to a sheet-georef JSON (see sanborn_georef for shape).",
    )
    parser.add_argument(
        "--city",
        default="flint",
        help="City slug for the emitted training records (default: flint).",
    )
    parser.add_argument(
        "--disable-ocr",
        action="store_true",
        help="Skip Tesseract story-count extraction (still runs vectorization).",
    )
    parser.add_argument("--commit-to-postgis", action="store_true")
    args = parser.parse_args(argv)

    if args.local_georef:
        ensure_ray_initialized()
        result = ray.get(
            ingest_local_sheet.remote(
                georef_json=args.local_georef,
                output_uri=args.output_uri,
                dry_run=not args.commit_to_postgis,
                commit_to_postgis=args.commit_to_postgis,
                enable_ocr=not args.disable_ocr,
                city=args.city,
            )
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    if args.sheet_id == 0:
        print(
            "Pass --sheet-id <Mapwarper-id> OR --local-georef path/to/sheet.georef.json"
        )
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
