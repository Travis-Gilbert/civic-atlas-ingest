"""Ray task: pull OSM building footprints + tags via Overpass.

Status: skeleton. Real implementation is pending finalization of
the BuildingPresence / ArtifactAnchor proto in
`our-civic-atlas-backend/proto/civic_atlas/v1/reconstruction.proto`.

For each city target:
  1. Build an Overpass QL query for `way["building"]` and
     `relation["building"]` within the bbox.
  2. Pull with backoff. Overpass is rate-limited; bursty Ray workers wait
     politely.
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
    ray job submit --working-dir . -- python -m civic_atlas_ingest.ingest_overpass detroit

Environment:
    CIVIC_ATLAS_GRPC_URL        URL of the Atlas backend
    CIVIC_ATLAS_CORPUS_TOKEN    bearer token for the corpus tenant
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .city_targets import CityTarget, get_target
from .coverage_quality import ProvenanceLane
from .runtime import ensure_ray_initialized, ray
from .training_corpus import (
    TrainingCorpusRecord,
    bbox_polygon,
    make_training_record,
    write_training_batch,
)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT_S = 180

# Bursty + rate-limit-friendly. Cluster scheduling controls max in-flight work.
@ray.remote(num_cpus=2, memory=4 * 1024 * 1024 * 1024)
def ingest_city(
    city: str,
    *,
    output_uri: str | None = None,
    fixture_json: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    limit: int = 0,
) -> dict[str, Any]:
    """Pull OSM buildings for one city and write to the Atlas backend.

    Returns a summary dict: { 'city', 'ways', 'relations',
    'records_written', 'mean_coverage_quality' }.
    """
    target = get_target(city)
    active_target = target if bbox is None else _target_with_bbox(target, bbox)
    query = _build_overpass_query(active_target)
    data = _load_fixture_or_fetch(fixture_json, query)
    records = _records_from_overpass(
        data,
        target=active_target,
        source_uri=OVERPASS_URL,
        limit=limit,
    )
    batch = write_training_batch(records, source="overpass", output_uri=output_uri)

    ways = sum(1 for item in data.get("elements", []) if item.get("type") == "way")
    relations = sum(1 for item in data.get("elements", []) if item.get("type") == "relation")
    mean_quality = (
        sum(record.coverage.quality for record in records) / len(records) if records else 0.0
    )
    return {
        "city": active_target.slug,
        "ways": ways,
        "relations": relations,
        "records_written": len(records),
        "mean_coverage_quality": round(mean_quality, 4),
        "query": query,
        "batch": batch.to_json(),
    }


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


def _decode_tags_to_fields(
    tags: dict[str, str],
) -> tuple[dict[str, Any], dict[str, ProvenanceLane]]:
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
        fields["start_date_raw"] = tags["start_date"]
        lanes["start_date_raw"] = ProvenanceLane.OSM_TAGGED

    if "name" in tags:
        fields["display_name"] = tags["name"]
        lanes["display_name"] = ProvenanceLane.OSM_TAGGED

    if "building" in tags:
        fields["building"] = tags["building"]
        lanes["building"] = ProvenanceLane.OSM_TAGGED

    if "amenity" in tags:
        fields["amenity"] = tags["amenity"]
        lanes["amenity"] = ProvenanceLane.OSM_TAGGED

    if "landuse" in tags:
        fields["landuse"] = tags["landuse"]
        lanes["landuse"] = ProvenanceLane.OSM_TAGGED

    return fields, lanes


def _records_from_overpass(
    data: dict[str, Any],
    *,
    target: CityTarget,
    source_uri: str,
    limit: int = 0,
) -> list[TrainingCorpusRecord]:
    records: list[TrainingCorpusRecord] = []
    for element in data.get("elements", []):
        if element.get("type") not in {"way", "relation"}:
            continue
        tags = element.get("tags", {})
        geometry = _element_geometry(element)
        if not geometry:
            geometry = bbox_polygon(*target.bbox)
        fields, lanes = _decode_tags_to_fields(tags)
        if not fields:
            fields = {"building": tags.get("building", "yes")}
            lanes = {"building": ProvenanceLane.FOOTPRINT_ONLY}
        records.append(
            make_training_record(
                source="overpass",
                source_id=f"{element.get('type')}:{element.get('id')}",
                city=target.slug,
                geometry=geometry,
                fields=fields,
                lanes=lanes,
                source_uri=source_uri,
                extra={"osm_type": element.get("type"), "osm_tags": tags},
            )
        )
        if limit and len(records) >= limit:
            break
    return records


def _element_geometry(element: dict[str, Any]) -> dict[str, Any] | None:
    raw_geometry = element.get("geometry")
    if not raw_geometry:
        return None
    coords = [[float(point["lon"]), float(point["lat"])] for point in raw_geometry]
    if len(coords) < 3:
        return {"type": "LineString", "coordinates": coords}
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}


def _load_fixture_or_fetch(fixture_json: str | None, query: str) -> dict[str, Any]:
    if fixture_json:
        return json.loads(_read_arg_or_path(fixture_json))

    import httpx

    response = httpx.post(
        OVERPASS_URL,
        data={"data": query},
        headers={"User-Agent": "civic-atlas-ingest/0.1"},
        timeout=OVERPASS_TIMEOUT_S + 30,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.json()


def _read_arg_or_path(value: str) -> str:
    if value.startswith("@"):
        return open(value[1:], encoding="utf-8").read()
    candidate = os.path.expanduser(value)
    if os.path.exists(candidate):
        return open(candidate, encoding="utf-8").read()
    return value


def _target_with_bbox(
    target: CityTarget,
    bbox: tuple[float, float, float, float],
) -> CityTarget:
    return CityTarget(
        slug=target.slug,
        display_name=target.display_name,
        state=target.state,
        bbox=bbox,
        assessor_public=target.assessor_public,
    )


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be min_lat,min_lon,max_lat,max_lon")
    return (parts[0], parts[1], parts[2], parts[3])


def main(argv: list[str] | None = None) -> None:
    """Local entrypoint for `ray job submit` or direct local smoke runs."""
    parser = argparse.ArgumentParser(description="Ingest OSM building records via Overpass")
    parser.add_argument("city", nargs="?", default="flint")
    parser.add_argument("--output-uri", default=None)
    parser.add_argument("--fixture-json", default=None)
    parser.add_argument("--bbox", type=_parse_bbox, default=None)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    ensure_ray_initialized()
    result = ray.get(
        ingest_city.remote(
            city=args.city,
            output_uri=args.output_uri,
            fixture_json=args.fixture_json,
            bbox=args.bbox,
            limit=args.limit,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))


# Discovery helper: makes the city list visible from the file directly.
if __name__ == "__main__" and os.environ.get("CIVIC_ATLAS_DISCOVER"):
    from .city_targets import CITY_TARGETS

    for t in CITY_TARGETS:
        print(t.slug, t.bbox)
elif __name__ == "__main__":
    main(sys.argv[1:])
