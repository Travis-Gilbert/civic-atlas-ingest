"""
Fetch the City of Flint parcel layer from the public ArcGIS Feature Service
at gis.cityofflint.com. Saves a single GeoJSON FeatureCollection to the
cache directory.

Source: source 1 from the Phase A implementation plan
(`docs/plans/atlas-typology-phase-a-implementation.md` in
Open-Flint-Atlas-main-release). The Parcels layer
(`ff65debe531c4c0392e4760628050070`) is public, no token required, and
carries Prop_Class (Michigan assessor code), Use_Type, and Zoning per
parcel. ~54,952 features total.

This is the LABEL SOURCE that replaces the spec's "Hand-label 200 buildings"
(A3-task-1) with a city-scale parcel-class-derived label per OSM building.
The spec accepts this path because:
  - the assessor's Prop_Class is the legal-record ground truth for property
    use classification, recorded by the City of Flint Assessor's Office,
  - the join is per-parcel at 54,952-scale vs. per-building at 200-scale,
  - it removes the human-bottleneck on training data.

Usage:
    python -m scripts.fetch_flint_parcels [--output PATH] [--force]

Run from civic-atlas-ingest root with the .venv active.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FEATURE_SERVICE_URL = (
    "https://services5.arcgis.com/lqqWNtSxx8Akj04A/"
    "arcgis/rest/services/Parcels/FeatureServer/0"
)

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "cache" / "flint_parcels.geojson"


def fetch_total_count() -> int:
    """Return the total feature count for the parcel layer."""
    url = f"{FEATURE_SERVICE_URL}/query?" + urlencode(
        {"where": "1=1", "returnCountOnly": "true", "f": "json"}
    )
    with urlopen(Request(url, headers={"User-Agent": "civic-atlas-ingest"})) as resp:
        payload = json.loads(resp.read())
    if "count" not in payload:
        raise RuntimeError(f"Unexpected count response: {payload}")
    return int(payload["count"])


def fetch_max_record_count() -> int:
    """Inspect the layer metadata for the server's per-request page size."""
    url = f"{FEATURE_SERVICE_URL}?f=json"
    with urlopen(Request(url, headers={"User-Agent": "civic-atlas-ingest"})) as resp:
        payload = json.loads(resp.read())
    return int(payload.get("maxRecordCount", 1000))


def fetch_page(offset: int, page_size: int) -> dict:
    """Fetch one page of features as GeoJSON. Returns a FeatureCollection dict."""
    url = f"{FEATURE_SERVICE_URL}/query?" + urlencode(
        {
            "where": "1=1",
            "outFields": "*",
            "outSR": "4326",  # WGS84 so it matches OSM coordinates
            "resultOffset": offset,
            "resultRecordCount": page_size,
            "f": "geojson",
        }
    )
    with urlopen(
        Request(url, headers={"User-Agent": "civic-atlas-ingest"}), timeout=60
    ) as resp:
        return json.loads(resp.read())


def fetch_all_features(page_size: int | None = None) -> dict:
    """Fetch every feature, paginating as needed. Returns a single FeatureCollection."""
    if page_size is None:
        page_size = fetch_max_record_count()
    total = fetch_total_count()
    print(f"Fetching {total} parcels in pages of {page_size}...", flush=True)
    features: list[dict] = []
    offset = 0
    while offset < total:
        page = fetch_page(offset, page_size)
        page_features = page.get("features", [])
        if not page_features:
            print(f"  empty page at offset {offset}, stopping early", flush=True)
            break
        features.extend(page_features)
        print(
            f"  offset {offset:>6} got {len(page_features):>5} features "
            f"(running total: {len(features):>5}/{total})",
            flush=True,
        )
        offset += len(page_features)
        time.sleep(0.2)  # gentle pacing
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": FEATURE_SERVICE_URL,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "feature_count": len(features),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if the output file already exists.",
    )
    args = parser.parse_args()

    if args.output.exists() and not args.force:
        print(f"{args.output} exists. Pass --force to re-download.", file=sys.stderr)
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    collection = fetch_all_features()
    args.output.write_text(json.dumps(collection))
    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(
        f"Wrote {len(collection['features'])} parcels to {args.output} "
        f"({size_mb:.1f} MB).",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
