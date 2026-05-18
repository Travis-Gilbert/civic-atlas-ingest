"""Modal app: pull OSM building footprints + tags via Overpass.

Status: skeleton. Real implementation is pending finalization of
the BuildingPresence / ArtifactAnchor proto in
`our-civic-atlas-backend/proto/civic_atlas/v1/reconstruction.proto`.

For each city target:
  1. Build an Overpass QL query for `way["building"]` and
     `relation["building"]` within the bbox.
  2. Pull with backoff. Overpass is rate-limited; bursty Modal
     workers wait politely.
  3. Decode tags into a sparse field bag:
     - building:levels => stories
     - height => height_m
     - building:material => primary_material
     - roof:shape => roof_type
     - roof:material => roof_material
     - start_date => time_start_ms
     - name => display_name
  4. Stamp `coverage_quality` per record via the merge_strongest
     helper, with lane=OSM_TAGGED for explicit tags and
     lane=OSM_INFERRED for fields the importer guessed.
  5. Write batched BuildingPresence + ArtifactAnchor records to
     the Atlas backend over gRPC, with tenant_id='corpus'.

Run:
    modal deploy modal/ingest_overpass.py
    modal run modal/ingest_overpass.py::ingest_city --city detroit

Environment:
    CIVIC_ATLAS_GRPC_URL        URL of the Atlas backend
    CIVIC_ATLAS_CORPUS_TOKEN    bearer token for the corpus tenant
"""

from __future__ import annotations

import os
from typing import Any

import modal

from .city_targets import CityTarget, get_target
from .coverage_quality import ProvenanceLane, merge_strongest

# Modal image. Heavy spatial deps live here, not in the host env.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "httpx>=0.27",
        "shapely>=2.0",
        "pyproj>=3.6",
        "grpcio>=1.65",
        "protobuf>=5.27",
        "tenacity>=8.2",
    )
)

app = modal.App("civic-atlas-ingest-overpass", image=image)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT_S = 180

# Bursty + rate-limit-friendly. Max 4 in flight against Overpass.
@app.function(
    timeout=60 * 30,
    cpu=2,
    memory=4096,
    secrets=[modal.Secret.from_name("civic-atlas-corpus")],
)
def ingest_city(city: str) -> dict[str, Any]:
    """Pull OSM buildings for one city and write to the Atlas backend.

    Returns a summary dict: { 'city', 'ways', 'relations',
    'records_written', 'mean_coverage_quality' }.
    """
    target = get_target(city)
    raise NotImplementedError(
        "Phase 5 stub. Implementation lands after the BuildingPresence "
        "proto is final in our-civic-atlas-backend. Until then, this "
        "function only validates the city slug and prints the bbox.\n"
        f"target={target!r}"
    )


def _build_overpass_query(target: CityTarget) -> str:
    """Build an Overpass QL query for buildings in the city bbox.

    Result format: JSON. Includes both 'way' and 'relation' buildings.
    Geometry is included via `out geom;` so we don't need a second pass.
    """
    s, w, n, e = target.bbox
    return f"""[out:json][timeout:{OVERPASS_TIMEOUT_S}];
(
  way["building"]({s},{w},{n},{e});
  relation["building"]({s},{w},{n},{e});
);
out geom tags;"""


def _decode_tags_to_fields(tags: dict[str, str]) -> tuple[dict[str, Any], dict[str, ProvenanceLane]]:
    """Map an OSM tag dict to (field_values, field_provenance).

    Only fields the building head will use are emitted. Unknown tags
    are dropped to keep payloads small.
    """
    fields: dict[str, Any] = {}
    lanes: dict[str, ProvenanceLane] = {}

    if "building:levels" in tags:
        try:
            fields["stories"] = int(tags["building:levels"])
            lanes["stories"] = ProvenanceLane.OSM_TAGGED
        except ValueError:
            pass

    if "height" in tags:
        try:
            fields["height_m"] = float(tags["height"].rstrip(" m"))
            lanes["height_m"] = ProvenanceLane.OSM_TAGGED
        except ValueError:
            pass

    if "building:material" in tags:
        fields["primary_material"] = tags["building:material"]
        lanes["primary_material"] = ProvenanceLane.OSM_TAGGED

    if "roof:shape" in tags:
        fields["roof_type"] = tags["roof:shape"]
        lanes["roof_type"] = ProvenanceLane.OSM_TAGGED

    if "roof:material" in tags:
        fields["roof_material"] = tags["roof:material"]
        lanes["roof_material"] = ProvenanceLane.OSM_TAGGED

    if "start_date" in tags:
        # OSM start_date is messy: "1898", "1898-04", "c. 1900", "1900s"
        # Real parsing lives in osm-utils; this is a stub.
        fields["start_date_raw"] = tags["start_date"]
        lanes["start_date_raw"] = ProvenanceLane.OSM_TAGGED

    if "name" in tags:
        fields["display_name"] = tags["name"]
        lanes["display_name"] = ProvenanceLane.OSM_TAGGED

    return fields, lanes


@app.local_entrypoint()
def main(city: str = "detroit") -> None:
    """Local entrypoint for `modal run`."""
    result = ingest_city.remote(city=city)
    print(result)


# Discovery helper: makes the city list visible from the file directly.
if __name__ == "__main__" and os.environ.get("CIVIC_ATLAS_DISCOVER"):
    from .city_targets import CITY_TARGETS

    for t in CITY_TARGETS:
        print(t.slug, t.bbox)
