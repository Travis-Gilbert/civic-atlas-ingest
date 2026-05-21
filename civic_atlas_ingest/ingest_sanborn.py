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

import os
import sys
from typing import Any

import ray

from .runtime import ensure_ray_initialized

DEFAULT_MAPWARPER_BASE = "https://mapwarper.net"


@ray.remote(num_cpus=4, memory=8 * 1024 * 1024 * 1024)
def ingest_sheet(
    sheet_id: int,
    *,
    dry_run: bool = True,
    commit_to_postgis: bool = False,
) -> dict[str, Any]:
    """Pull a single Sanborn sheet, vectorize buildings, optionally commit.

    `dry_run` writes only the spot-check GeoJSON to the attached volume.
    `commit_to_postgis` requires a moderator's eye on the spot-check
    output first.

    Returns { 'sheet_id', 'polygons', 'mean_coverage_quality',
              'spotcheck_path', 'records_written' }.
    """
    if dry_run and commit_to_postgis:
        raise ValueError("cannot dry_run AND commit_to_postgis simultaneously")
    raise NotImplementedError(
        "Phase 5 stub. Implementation lands after:\n"
        "  - BuildingPresence proto is final\n"
        "  - Sanborn color-decoder module ships (docs/sanborn-key.md)\n"
        f"sheet_id={sheet_id}, dry_run={dry_run}, commit_to_postgis={commit_to_postgis}"
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
    raise NotImplementedError(
        f"Phase 5 stub. bbox=({min_lat},{min_lon},{max_lat},{max_lon})"
    )


def main(sheet_id: int = 0, dry_run: bool = True) -> None:
    """Local entrypoint for `ray job submit` or direct local smoke runs."""
    if sheet_id == 0:
        print("Pass --sheet-id <id>. Use list_sheets_for_bbox to discover IDs.")
        return
    ensure_ray_initialized()
    result = ray.get(ingest_sheet.remote(sheet_id=sheet_id, dry_run=dry_run))
    print(result)


_MAPWARPER_BASE = os.environ.get("MAPWARPER_BASE_URL", DEFAULT_MAPWARPER_BASE)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
