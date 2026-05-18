"""Modal app: ingest per-city assessor parcel records.

Status: skeleton. Each city has its own assessor data format and
publication channel. The plan is one Modal entrypoint per city,
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
    modal deploy modal/ingest_assessor.py
    modal run modal/ingest_assessor.py::ingest_city --city detroit

Environment:
    CIVIC_ATLAS_GRPC_URL        URL of the Atlas backend
    CIVIC_ATLAS_CORPUS_TOKEN    bearer token for the corpus tenant
"""

from __future__ import annotations

from typing import Any

import modal

from .city_targets import CITY_TARGETS, CityTarget, get_target

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgdal-dev", "gdal-bin", "libgeos-dev")
    .pip_install(
        "httpx>=0.27",
        "shapely>=2.0",
        "pyproj>=3.6",
        "geopandas>=0.14",
        "pandas>=2.1",
        "grpcio>=1.65",
        "protobuf>=5.27",
    )
)

app = modal.App("civic-atlas-ingest-assessor", image=image)


# Per-city assessor source URLs. Each entry is either a single URL
# (GeoJSON/CSV) or a REST endpoint base + layer config. Empty list
# means the city's assessor data is not publicly retrievable.
_ASSESSOR_SOURCES: dict[str, list[str]] = {
    "detroit":   ["https://data.detroitmi.gov/api/.../parcels"],          # TODO real URL
    "buffalo":   ["https://data.buffalony.gov/api/.../parcels"],          # TODO
    "cleveland": ["https://data.cuyahogacounty.us/.../assessor"],         # TODO
    "pittsburgh":["https://data.alleghenycounty.us/.../parcels"],         # TODO
    "toledo":    ["https://data.lucascountyoh.gov/.../parcels"],          # TODO
    "akron":     ["https://data.summitoh.net/.../parcels"],               # TODO
    "milwaukee": ["https://data.milwaukee.gov/.../parcels"],              # TODO
    "saginaw":   [],   # not publicly downloadable as of 2026-05-18
    "bay-city":  [],   # not publicly downloadable as of 2026-05-18
    "youngstown":["https://data.mahoningcountyoh.gov/.../parcels"],       # TODO
}


@app.function(
    timeout=60 * 60,
    cpu=4,
    memory=8192,
    secrets=[modal.Secret.from_name("civic-atlas-corpus")],
)
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


@app.function(timeout=60 * 5)
def status() -> dict[str, list[str]]:
    """Return the configured-vs-skipped breakdown across all targets."""
    configured = [t.slug for t in CITY_TARGETS if _ASSESSOR_SOURCES.get(t.slug)]
    skipped = [t.slug for t in CITY_TARGETS if not _ASSESSOR_SOURCES.get(t.slug)]
    return {"configured": configured, "skipped": skipped}


@app.local_entrypoint()
def main(city: str = "detroit") -> None:
    """Local entrypoint for `modal run`."""
    result = ingest_city.remote(city=city)
    print(result)
