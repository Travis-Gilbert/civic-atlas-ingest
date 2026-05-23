"""Phase A.5 → Phase B archetype bridge.

Maps a Phase A.5 BuildingFabricArchetype (present_residential_single,
present_commercial, etc. — the chipboard-render taxonomy) onto one
of the 8 Phase B procedural archetypes that scene_foundry.render
already knows how to render:

    commercial-brick-two-story
    frame-house-with-porch
    factory-bay
    warehouse
    church
    school
    gas-station
    mixed-use-storefront

And converts Phase A.5 per-OSM-building parameters (height_m, stories,
roof pitch, footprint geometry, classifier confidence) into the spec
JSON shape that `primitives/scripts/render_spec.py` reads to drive
Blender's procedural builders.

The Phase B archetypes are a strict superset of what Phase A.5 needs
for present-day rendering: every Phase A.5 archetype maps to exactly
one Phase B builder, with footprint shape and OSM name regex
sub-routing the ambiguous cases (industrial → factory-bay vs warehouse
by aspect ratio; civic → church vs school by name).

`present_unknown` deliberately has no Phase B mapping — those
buildings render only as the chipboard mass and skip GLB generation.
The frontend's existing chipboard render handles them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from math import cos, hypot, pi
from typing import Any


# ── Archetype mapping ───────────────────────────────────────────────


@dataclass(frozen=True)
class FabricMappingDecision:
    """The Phase B archetype slug + the dimensional inputs the
    `render_spec.py` builders read."""

    phase_b_slug: str
    width_m: float
    depth_m: float
    height_m: float
    stories: int
    roof_pitch_degrees: float
    roof_material: str
    facade_color: str
    front_edge_bearing_degrees: float
    variation_seed: int
    bay_count: int
    floor_count: int


# Phase B archetype slugs we route to. Kept here to fail loudly if the
# Phase B `ARCHETYPES` registry ever drops one of these.
PHASE_B_SLUGS = frozenset(
    {
        "commercial-brick-two-story",
        "frame-house-with-porch",
        "factory-bay",
        "warehouse",
        "church",
        "school",
        "gas-station",
        "mixed-use-storefront",
    }
)


def map_fabric_to_phase_b(
    *,
    fabric_archetype: str,
    typology_class: str | None,
    osm_name: str | None,
    osm_building_tag: str | None,
    footprint_area_m2: float,
    footprint_ratio: float,
    height_m: float,
    stories: int,
    roof_pitch_degrees: float,
    roof_material: str,
    facade_color: str,
    front_edge_bearing_degrees: float,
    variation_seed: int,
    window_spacing_m: float,
) -> FabricMappingDecision | None:
    """Decide which Phase B archetype to render for a Phase A.5 building.

    Returns None for `present_unknown` (no GLB) and for buildings
    smaller than 40 m² (sheds, garages — chipboard is enough).

    Returns a FabricMappingDecision otherwise. The decision carries
    the dimensional inputs the procedural builders consume.
    """
    if fabric_archetype == "present_unknown":
        return None
    if footprint_area_m2 < 40:
        return None

    width_m, depth_m = _derive_rect_dims(
        footprint_area_m2=footprint_area_m2,
        footprint_ratio=footprint_ratio,
    )
    bay_count = max(2, min(8, int(width_m // max(window_spacing_m, 1.5))))
    floor_count = max(1, min(8, stories))

    phase_b_slug = _route_to_phase_b(
        fabric_archetype=fabric_archetype,
        typology_class=typology_class,
        osm_name=osm_name,
        osm_building_tag=osm_building_tag,
        footprint_area_m2=footprint_area_m2,
        footprint_ratio=footprint_ratio,
    )
    if phase_b_slug not in PHASE_B_SLUGS:
        raise ValueError(
            f"Phase A.5 → Phase B mapping produced unknown slug "
            f"{phase_b_slug!r} (registry: {sorted(PHASE_B_SLUGS)})"
        )

    return FabricMappingDecision(
        phase_b_slug=phase_b_slug,
        width_m=width_m,
        depth_m=depth_m,
        height_m=height_m,
        stories=stories,
        roof_pitch_degrees=roof_pitch_degrees,
        roof_material=roof_material,
        facade_color=facade_color,
        front_edge_bearing_degrees=front_edge_bearing_degrees,
        variation_seed=variation_seed,
        bay_count=bay_count,
        floor_count=floor_count,
    )


_CHURCH_NAME_PATTERN = re.compile(
    r"\b(?:church|cathedral|chapel|mosque|temple|synagogue|"
    r"presbyter|methodist|baptist|catholic|episcopal|lutheran|"
    r"evangelical|pentecostal|congregation|parish)\b",
    re.IGNORECASE,
)
_SCHOOL_NAME_PATTERN = re.compile(
    r"\b(?:school|academy|college|university|elementary|middle|high|"
    r"library|museum|community center|youth center)\b",
    re.IGNORECASE,
)
_GAS_STATION_NAME_PATTERN = re.compile(
    r"\b(?:gas station|fuel|petroleum|exxon|chevron|shell|bp |sunoco|"
    r"speedway|marathon|7-?eleven)\b",
    re.IGNORECASE,
)


def _route_to_phase_b(
    *,
    fabric_archetype: str,
    typology_class: str | None,
    osm_name: str | None,
    osm_building_tag: str | None,
    footprint_area_m2: float,
    footprint_ratio: float,
) -> str:
    """Phase A.5 archetype → Phase B slug with sub-routing on geometry + name."""

    name = osm_name or ""
    tag = (osm_building_tag or "").lower()

    if fabric_archetype == "present_civic":
        if _CHURCH_NAME_PATTERN.search(name) or tag in {"church", "cathedral", "chapel"}:
            return "church"
        # Default civic = school. The Phase B `school` builder produces a
        # 3-story brick block with central entry — fits libraries,
        # museums, government, and schools cleanly.
        return "school"

    if fabric_archetype == "present_industrial":
        # Long-and-narrow industrial = assembly-line factory_bay
        # (sawtooth roof). Wider/squarer industrial = warehouse
        # (flat roof, loading doors).
        if footprint_ratio > 2.6:
            return "factory-bay"
        return "warehouse"

    if fabric_archetype == "present_commercial":
        # OSM-tag named gas stations route to their own builder.
        if (
            _GAS_STATION_NAME_PATTERN.search(name)
            or tag in {"fuel", "service"}
        ):
            return "gas-station"
        return "commercial-brick-two-story"

    if fabric_archetype == "present_mixed_use":
        return "mixed-use-storefront"

    if fabric_archetype in {"present_residential_single", "present_residential_multi"}:
        # Both residential variants use frame_house_with_porch; the
        # multi case is parameterized via story_count + bay_count.
        return "frame-house-with-porch"

    # Shouldn't reach here — every Phase A.5 archetype enumerates
    # explicitly above. If a future archetype lands without a mapping,
    # fail loudly rather than silently fall through.
    raise ValueError(
        f"no Phase B archetype mapping defined for {fabric_archetype!r}"
    )


def _derive_rect_dims(
    *,
    footprint_area_m2: float,
    footprint_ratio: float,
) -> tuple[float, float]:
    """Derive (width, depth) in meters from area + aspect ratio.

    Phase B builders operate on a rectangular bounding-box assumption.
    The Phase A.5 OrientedFootprint frame already produces frontage
    and depth values, but those aren't threaded into this module yet —
    `footprint_ratio` is the lng-aligned bbox ratio, which is close
    enough for the procedural builders that read `width` / `depth`
    as the long/short axes.

    Returns (long_axis_m, short_axis_m).
    """
    if footprint_area_m2 <= 0 or footprint_ratio <= 0:
        return (10.0, 10.0)
    short = (footprint_area_m2 / footprint_ratio) ** 0.5
    long_ = short * footprint_ratio
    return (long_, short)


# ── Spec JSON translation ───────────────────────────────────────────


def fabric_decision_to_spec_json(
    *,
    osm_id: int | str,
    decision: FabricMappingDecision,
    spec_version: int = 1,
) -> dict[str, Any]:
    """Build the spec JSON `scene_foundry.render` + `render_spec.py` consume.

    The spec shape is documented in
    `primitives/archetypes/<slug>/__init__.py::MANIFEST::spec_fields_used`.
    Each Phase B builder reads a subset of the spec; the shape below
    is a superset that satisfies all 8 builders.

    spec_id is keyed off the OSM id so two identical Phase A.5
    inputs hit the same content-addressed S3 path.
    """
    return {
        "spec_id": f"fabric:osm:{osm_id}",
        "spec_version": spec_version,
        "display_name": f"OSM building {osm_id}",
        "tenant_context": {"tenant_id": "flint"},
        "mass": {
            "form": "rectangular_extrusion",
            "height": {"max": float(decision.height_m)},
            "width": {"max": float(decision.width_m)},
            "depth": {"max": float(decision.depth_m)},
            "story_count": int(decision.stories),
        },
        "facades": [
            {
                "material": decision.facade_color,
                "color": decision.facade_color,
                "opening_grids": [
                    {
                        "bay_count": decision.bay_count,
                        "floor_count": decision.floor_count,
                        "opening_type": "window",
                    }
                ],
            }
        ],
        "roof": {
            "form": _roof_form_for_slug(decision.phase_b_slug),
            "material": decision.roof_material,
            "pitch_degrees": float(decision.roof_pitch_degrees),
        },
        "ground_floor": {
            "entry_location": "front_center",
        },
        "ornaments": _ornaments_for_slug(decision.phase_b_slug),
        # Phase A.5 metadata so downstream consumers can identify the
        # provenance of this spec without parsing the spec_id.
        "metadata": {
            "archetype_slug": decision.phase_b_slug,
            "phase_a5_source": True,
            "osm_id": str(osm_id),
            "variation_seed": int(decision.variation_seed),
            "front_edge_bearing_degrees": float(
                decision.front_edge_bearing_degrees
            ),
        },
    }


def _roof_form_for_slug(slug: str) -> str:
    """Map archetype slug → roof form string for the spec."""
    return {
        "frame-house-with-porch": "gable",
        "commercial-brick-two-story": "flat",
        "factory-bay": "sawtooth",
        "warehouse": "flat",
        "church": "gable",
        "school": "flat",
        "gas-station": "flat",
        "mixed-use-storefront": "flat",
    }[slug]


def _ornaments_for_slug(slug: str) -> list[dict[str, str]]:
    """Default ornament list per Phase B archetype.

    The procedural builders read ornaments[] entries to decide
    porch presence, cornice presence, etc. Here we apply sensible
    defaults; per-OSM-building ornament variation can come later
    from the variation_seed.
    """
    if slug == "frame-house-with-porch":
        return [{"kind": "porch", "location": "front", "material": "WoodClapboard"}]
    if slug == "commercial-brick-two-story":
        return [{"kind": "cornice", "location": "top", "material": "StampedMetal"}]
    if slug == "mixed-use-storefront":
        return [
            {"kind": "cornice", "location": "top", "material": "StampedMetal"},
            {"kind": "awning", "location": "storefront", "material": "CanvasAwning"},
        ]
    if slug == "church":
        return [{"kind": "tower", "location": "front", "material": "Limestone"}]
    return []
