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

import sys
from typing import Any

import ray

from .city_targets import CITY_TARGETS, get_target
from .runtime import ensure_ray_initialized

# Per-city assessor source URLs. Each entry is either a single URL
# (GeoJSON/CSV) or a REST endpoint base + layer config. Empty list
# means the city's assessor data is not publicly retrievable.
_ASSESSOR_SOURCES: dict[str, list[str]] = {
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
def ingest_city(city: str) -> dict[str, Any]:
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

    raise NotImplementedError(
        "Phase 5 stub. Implementation lands after:\n"
        "  - BuildingPresence proto is final\n"
        "  - Per-city assessor column maps are catalogued in docs/assessor-maps.md\n"
        f"city={city}, sources={sources}"
    )


@ray.remote(num_cpus=1)
def status() -> dict[str, list[str]]:
    """Return the configured-vs-skipped breakdown across all targets."""
    configured = [t.slug for t in CITY_TARGETS if _ASSESSOR_SOURCES.get(t.slug)]
    skipped = [t.slug for t in CITY_TARGETS if not _ASSESSOR_SOURCES.get(t.slug)]
    return {"configured": configured, "skipped": skipped}


def main(city: str = "detroit") -> None:
    """Local entrypoint for `ray job submit` or direct local smoke runs."""
    ensure_ray_initialized()
    result = ray.get(ingest_city.remote(city=city))
    print(result)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "detroit")
