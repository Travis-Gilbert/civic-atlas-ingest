"""Phase A.5 batch driver: render a GLB for every Flint OSM building.

Iterates the Phase A typology-enriched OSM fixture, derives Phase A.5
fabric parameters for each building via `deriveBuildingFabricSpec` in
the frontend code (mirrored here in Python — see TODO below for
sharing the logic), maps to a Phase B archetype, builds the spec JSON
that `scene_foundry.render.remote()` consumes, and submits one Ray
remote call per building.

Output: `src/data/open-flint-atlas/fixtures/building-fabric/glbs.json`
in the Open-Flint-Atlas repo, keyed by osm_id, with `{glb_uri,
content_hash, archetype_slug, openbim_uri}` per row. The frontend's
fabric GLB layer (AtlasMap.tsx ScenegraphLayer at zoom >= 16) reads
this fixture to map osm_id -> glb_uri at runtime.

Operational notes:

 - Requires a live Ray cluster reachable from the submitting host.
   The `runpod.yaml` shape defines `ray.worker.scene_foundry` with
   the `civic-atlas/ray-blender:4.2-py311` image; provision and
   start the cluster manually per `ray_cluster/README.md` first.
 - Total cost scales with fleet size + per-render time. Empirically
   the procedural builders run in seconds per spec, but Blender
   startup is ~5-10s per invocation. Plan accordingly when sizing
   the worker pool.
 - Re-runnable: spec_id is keyed off osm_id, so re-submitting an
   unchanged spec hits the same content-addressed S3 path. The Ray
   task is idempotent for the same (spec_id, spec_version) pair.

Usage:

    cd civic-atlas-ingest
    ray job submit --working-dir . -- python -m scripts.build_flint_fabric_glbs \\
        [--limit N]          # only render the first N buildings
        [--dry-run]          # build specs but don't submit to Ray
        [--out PATH]         # override fixture path
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

from civic_atlas_ingest.fabric_archetype_mapping import (
    FabricMappingDecision,
    fabric_decision_to_spec_json,
    map_fabric_to_phase_b,
)


REPO_ROOT = Path(__file__).resolve().parent.parent

OPEN_FLINT_ATLAS_ROOT = Path(
    "/Users/travisgilbert/Tech Dev Local/Creative/Website/Open-Flint-Atlas-main-release"
)
OSM_FIXTURE_PATH = (
    OPEN_FLINT_ATLAS_ROOT
    / "src"
    / "data"
    / "open-flint-atlas"
    / "fixtures"
    / "osm-buildings.json"
)
DEFAULT_OUT_PATH = (
    OPEN_FLINT_ATLAS_ROOT
    / "src"
    / "data"
    / "open-flint-atlas"
    / "fixtures"
    / "building-fabric"
    / "glbs.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    parser.add_argument(
        "--osm-fixture", type=Path, default=OSM_FIXTURE_PATH,
        help="Path to the typology-enriched OSM fixture.",
    )
    args = parser.parse_args()

    print(f"Reading {args.osm_fixture}", flush=True)
    osm = json.loads(args.osm_fixture.read_text())
    features = osm.get("features", [])
    if args.limit > 0:
        features = features[: args.limit]
    print(f"Processing {len(features)} buildings", flush=True)

    # Build specs in pure Python (no Ray dependency for the spec build).
    specs: list[tuple[str, FabricMappingDecision, dict[str, Any]]] = []
    skipped_unknown = 0
    skipped_tiny = 0
    for feature in features:
        props = feature.get("properties", {})
        decision = _build_decision_for_feature(props, feature.get("geometry"))
        if decision is None:
            if (props.get("typology_class") or "").lower() == "unknown":
                skipped_unknown += 1
            else:
                skipped_tiny += 1
            continue
        osm_id = props.get("osm_id")
        if osm_id is None:
            continue
        spec_json = fabric_decision_to_spec_json(osm_id=osm_id, decision=decision)
        specs.append((str(osm_id), decision, spec_json))

    print(
        f"  built {len(specs)} specs ready to render; "
        f"skipped {skipped_unknown} unknowns + {skipped_tiny} tiny footprints",
        flush=True,
    )
    print("  archetype distribution:")
    archetype_counts: dict[str, int] = {}
    for _, decision, _ in specs:
        archetype_counts[decision.phase_b_slug] = (
            archetype_counts.get(decision.phase_b_slug, 0) + 1
        )
    for slug, count in sorted(archetype_counts.items(), key=lambda x: -x[1]):
        print(f"    {slug:>30}  {count:>6}")

    if args.dry_run:
        print("\n--dry-run set; skipping Ray submission.", flush=True)
        # Still write a manifest so the frontend can see what would
        # have been rendered.
        args.out.parent.mkdir(parents=True, exist_ok=True)
        dry_manifest = {
            "phase": "phase_a5_glb_pipeline",
            "status": "dry_run",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "spec_count": len(specs),
            "archetype_distribution": archetype_counts,
            "buildings": {
                osm_id: {
                    "spec_id": spec["spec_id"],
                    "archetype_slug": decision.phase_b_slug,
                    "glb_uri": None,
                    "glb_status": "dry_run_no_submission",
                }
                for osm_id, decision, spec in specs
            },
        }
        args.out.write_text(json.dumps(dry_manifest, indent=2))
        print(f"  wrote dry-run manifest to {args.out}", flush=True)
        return 0

    # Ray submission path. Import here so --dry-run works without Ray.
    print("\nSubmitting Ray render jobs...", flush=True)
    try:
        from civic_atlas_ingest.runtime import ensure_ray_initialized, ray
        from civic_atlas_ingest.scene_foundry import render
    except ImportError as exc:
        print(f"ray + scene_foundry import failed: {exc}", file=sys.stderr)
        print(
            "Submit from inside an environment that has Ray + civic-atlas-ingest "
            "installed (e.g. inside the Ray cluster worker, or via "
            "`ray job submit --working-dir . -- python -m scripts.build_flint_fabric_glbs`).",
            file=sys.stderr,
        )
        return 2

    ensure_ray_initialized()
    refs = []
    for osm_id, decision, spec_json in specs:
        refs.append(
            (
                osm_id,
                decision,
                render.remote(
                    spec_json=json.dumps(spec_json),
                    archetype=decision.phase_b_slug,
                    tenant="flint",
                    spec_id=spec_json["spec_id"],
                    spec_version=spec_json["spec_version"],
                ),
            )
        )

    print(f"  submitted {len(refs)} jobs; waiting for completion", flush=True)
    results: dict[str, dict[str, Any]] = {}
    completed = 0
    for osm_id, decision, ref in refs:
        try:
            result = ray.get(ref)
            results[osm_id] = {
                "spec_id": f"fabric:osm:{osm_id}",
                "archetype_slug": decision.phase_b_slug,
                "glb_uri": result["uri"],
                "content_hash": result["content_hash"],
                "openbim_uri": result.get("openbim_uri"),
                "openbim_hash": result.get("openbim_hash"),
                "archetype_hash": result.get("archetype_hash"),
                "glb_status": "rendered",
            }
        except Exception as exc:  # noqa: BLE001
            results[osm_id] = {
                "spec_id": f"fabric:osm:{osm_id}",
                "archetype_slug": decision.phase_b_slug,
                "glb_uri": None,
                "glb_status": "failed",
                "error": str(exc),
            }
        completed += 1
        if completed % 100 == 0:
            print(f"    {completed}/{len(refs)} completed", flush=True)

    print(
        f"  done. {sum(1 for r in results.values() if r['glb_status'] == 'rendered')} "
        f"rendered, "
        f"{sum(1 for r in results.values() if r['glb_status'] == 'failed')} failed",
        flush=True,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "phase": "phase_a5_glb_pipeline",
        "status": "rendered",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "spec_count": len(specs),
        "archetype_distribution": archetype_counts,
        "buildings": results,
    }
    args.out.write_text(json.dumps(manifest, indent=2))
    print(f"  wrote {args.out}", flush=True)
    return 0


# ── Per-feature parameter derivation ────────────────────────────────


# Mirror the relevant fields from src/lib/atlas/building-fabric.ts so the
# Python orchestrator and the TypeScript renderer agree on the
# archetype + height + roof pitch for each OSM row. When this drifts
# from the TS implementation, the renderer and the GLB stop matching;
# keep them aligned by hand.
_STORY_HEIGHT_M = 3.5

_ARCHETYPE_HEIGHT_PRIORS: dict[str, dict[str, Any]] = {
    "present_residential_single": {
        "baseline_stories": 1,
        "area_story_steps": [(200, 2)],
        "roof_pitch_default": 25.0,
        "roof_material": "asphalt",
        "facade_color": "#d8c7aa",
    },
    "present_residential_multi": {
        "baseline_stories": 3,
        "area_story_steps": [(600, 4), (1200, 5)],
        "roof_pitch_default": 5.0,
        "roof_material": "membrane",
        "facade_color": "#cfc7b8",
    },
    "present_commercial": {
        "baseline_stories": 1,
        "area_story_steps": [(400, 2)],
        "roof_pitch_default": 0.0,
        "roof_material": "membrane",
        "facade_color": "#d6c2a5",
    },
    "present_industrial": {
        "baseline_stories": 1,
        "area_story_steps": [],
        "height_m_override": 10.0,
        "roof_pitch_default": 8.0,
        "roof_material": "metal",
        "facade_color": "#c3c1ba",
    },
    "present_civic": {
        "baseline_stories": 2,
        "area_story_steps": [],
        "roof_pitch_default": 20.0,
        "roof_material": "tile",
        "facade_color": "#ddd2bd",
    },
    "present_mixed_use": {
        "baseline_stories": 3,
        "area_story_steps": [],
        "roof_pitch_default": 0.0,
        "roof_material": "membrane",
        "facade_color": "#d9cab0",
    },
}


def _build_decision_for_feature(
    props: dict[str, Any],
    geometry: dict[str, Any] | None,
) -> FabricMappingDecision | None:
    """Derive (Phase A.5 archetype, dimensional params) for one OSM row.

    Combines the OSM property fields (typology_class, building tag,
    height, levels) with the footprint geometry to produce the
    inputs `map_fabric_to_phase_b` needs. Mirrors the per-row logic
    from `deriveBuildingFabricSpec` in
    src/lib/atlas/building-fabric.ts.
    """
    if geometry is None:
        return None
    area_m2, ratio = _footprint_area_and_ratio(geometry)
    if area_m2 <= 0:
        return None

    typology_class = (props.get("typology_class") or "").lower() or None
    typology_confidence = props.get("typology_confidence")
    building_tag = props.get("building")
    osm_name = props.get("name")
    height_meters = props.get("height_meters")
    levels = props.get("levels")
    osm_id_for_seed = str(props.get("osm_id") or "")

    fabric_archetype = _classify_fabric_archetype(
        typology_class=typology_class,
        typology_confidence=(
            float(typology_confidence)
            if isinstance(typology_confidence, (int, float))
            else None
        ),
        building_tag=building_tag,
        name=osm_name,
        footprint_area_m2=area_m2,
        footprint_ratio=ratio,
    )
    prior = _ARCHETYPE_HEIGHT_PRIORS.get(fabric_archetype)
    if prior is None:
        # present_unknown — no GLB
        return None

    stories = _infer_stories(area_m2, height_meters, levels, prior)
    height_m = (
        float(height_meters)
        if isinstance(height_meters, (int, float)) and height_meters > 0
        else prior.get("height_m_override")
        or stories * _STORY_HEIGHT_M
    )
    height_m = max(2.5, min(80.0, height_m))
    variation_seed = _stable_hash(osm_id_for_seed)
    roof_pitch = float(prior["roof_pitch_default"])

    # Construct the Phase A.5 → Phase B decision via the bridge module.
    return map_fabric_to_phase_b(
        fabric_archetype=fabric_archetype,
        typology_class=typology_class,
        osm_name=osm_name,
        osm_building_tag=building_tag,
        footprint_area_m2=area_m2,
        footprint_ratio=ratio,
        height_m=height_m,
        stories=stories,
        roof_pitch_degrees=roof_pitch,
        roof_material=prior["roof_material"],
        facade_color=prior["facade_color"],
        front_edge_bearing_degrees=_longest_edge_bearing(geometry),
        variation_seed=variation_seed,
        window_spacing_m=3.0,  # average between residential / commercial defaults
    )


def _classify_fabric_archetype(
    *,
    typology_class: str | None,
    typology_confidence: float | None,
    building_tag: str | None,
    name: str | None,
    footprint_area_m2: float,
    footprint_ratio: float,
) -> str:
    """Mirror of classifyPresentArchetype in building-fabric.ts (post-Step-0).

    When typology_confidence >= 0.6, the classifier output drives the
    archetype family with footprint area / ratio picking the
    sub-archetype. Falls through to OSM-tag regex for low-confidence
    or unknown rows.
    """
    use_typology = (
        typology_confidence is not None
        and typology_confidence >= 0.6
        and typology_class is not None
        and footprint_area_m2 >= 60
    )
    area = footprint_area_m2

    if use_typology:
        if typology_class == "civic":
            return "present_civic"
        if typology_class == "industrial":
            return "present_industrial"
        if typology_class == "commercial":
            return (
                "present_mixed_use" if area > 600 else "present_commercial"
            )
        if typology_class == "residential":
            return (
                "present_residential_multi"
                if area > 600
                else "present_residential_single"
            )
        if typology_class == "mixed_use":
            return "present_mixed_use"
        # unknown falls through to regex tier

    combined = " ".join(
        [building_tag or "", name or ""]
    ).lower()
    if any(
        token in combined
        for token in (
            "church",
            "school",
            "college",
            "university",
            "library",
            "hospital",
            "clinic",
            "courthouse",
            "museum",
            "theatre",
            "theater",
            "government",
        )
    ):
        return "present_civic"
    if any(
        token in combined
        for token in (
            "industrial",
            "warehouse",
            "manufacturing",
            "hangar",
            "depot",
            "plant",
            "factory",
        )
    ):
        return "present_industrial"
    if any(token in combined for token in ("apartments", "multifamily", "dormitory")):
        return "present_residential_multi"
    if any(
        token in combined
        for token in (
            "retail",
            "commercial",
            "office",
            "hotel",
            "shop",
            "store",
            "restaurant",
            "bank",
        )
    ):
        return "present_commercial"
    if any(
        token in combined
        for token in (
            "house",
            "detached",
            "semidetached",
            "terrace",
            "residential",
            "garage",
        )
    ):
        return (
            "present_residential_multi"
            if area > 600
            else "present_residential_single"
        )
    if area > 5600 and footprint_ratio > 2.2:
        return "present_industrial"
    return "present_unknown"


def _infer_stories(
    area_m2: float,
    height_meters: Any,
    levels: Any,
    prior: dict[str, Any],
) -> int:
    if isinstance(levels, (int, float)) and levels > 0:
        return max(1, min(12, int(round(levels))))
    if isinstance(height_meters, (int, float)) and height_meters > 0:
        return max(1, min(12, int(round(height_meters / _STORY_HEIGHT_M))))
    stories = int(prior["baseline_stories"])
    for min_area, step_stories in prior["area_story_steps"]:
        if area_m2 > min_area:
            stories = step_stories
    return stories


# ── Geometry helpers ────────────────────────────────────────────────


def _footprint_area_and_ratio(
    geometry: dict[str, Any],
) -> tuple[float, float]:
    """Lng-aligned bbox area + aspect ratio in meters."""
    ring = _outer_ring(geometry)
    if not ring or len(ring) < 4:
        return (0.0, 0.0)
    lngs = [coord[0] for coord in ring]
    lats = [coord[1] for coord in ring]
    west, east = min(lngs), max(lngs)
    south, north = min(lats), max(lats)
    if east <= west or north <= south:
        return (0.0, 0.0)
    center_lat = (south + north) / 2
    meters_per_lat = 111320.0
    meters_per_lng = math.cos(center_lat * math.pi / 180) * meters_per_lat
    width_m = abs((east - west) * meters_per_lng)
    depth_m = abs((north - south) * meters_per_lat)
    area = max(1.0, width_m * depth_m)
    ratio = max(width_m, depth_m) / max(1.0, min(width_m, depth_m))
    return (area, ratio)


def _longest_edge_bearing(geometry: dict[str, Any]) -> float:
    ring = _outer_ring(geometry)
    if not ring or len(ring) < 2:
        return 0.0
    longest = 0.0
    bearing = 0.0
    for i in range(len(ring) - 1):
        a, b = ring[i], ring[i + 1]
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        center_lat = (a[1] + b[1]) / 2 * math.pi / 180
        meters_x = dx * math.cos(center_lat) * 111320.0
        meters_y = dy * 111320.0
        dist = math.hypot(meters_x, meters_y)
        if dist > longest:
            longest = dist
            # Compass bearing 0 = north, clockwise.
            angle_rad = math.atan2(meters_x, meters_y)
            bearing = (angle_rad * 180 / math.pi + 360) % 360
    return bearing


def _outer_ring(geometry: dict[str, Any]) -> list[list[float]]:
    if not isinstance(geometry, dict):
        return []
    if geometry.get("type") == "Polygon":
        coords = geometry.get("coordinates") or [[]]
        return coords[0] if coords else []
    if geometry.get("type") == "MultiPolygon":
        coords = geometry.get("coordinates") or [[[]]]
        return coords[0][0] if coords and coords[0] else []
    return []


def _stable_hash(value: str) -> int:
    """FNV-1a 32-bit. Mirrors stableHash in building-fabric.ts."""
    h = 2166136261
    for ch in value:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


if __name__ == "__main__":
    raise SystemExit(main())
