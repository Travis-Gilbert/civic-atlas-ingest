"""Archetype: mid-century gas station (canopy + service bay + pump island).

Canopy supports come from mass.width and the number of pump islands
in `mass.attributes.pump_islands`. Service bay is optional via
`ground_floor.has_service_bay=true`.
"""

from __future__ import annotations

MANIFEST = {
    "slug": "gas-station",
    "blend_file": "archetype.blend",
    "description": "Mid-century gas station, canopy + pump island + optional service bay",
    "spec_fields_used": [
        "mass.height.max",
        "mass.width.max",
        "mass.depth.max",
        "mass.attributes",
        "facades[0].material",
        "ground_floor.use_type",
        "ground_floor.has_awning",
        "roof.form",
        "roof.material",
    ],
    "material_slots": [
        {"slot_name": "Cladding", "spec_field_path": "facades[0].material",
         "fallback_material": "PorcelainEnamel"},
        {"slot_name": "Canopy", "spec_field_path": "roof.material",
         "fallback_material": "BuildupRoofing"},
        {"slot_name": "PumpIsland", "spec_field_path": "mass.attributes",
         "fallback_material": "PaintedSteel"},
    ],
    "geometry_nodes_group_name": "GasStation",
    "render_hints": {
        "scale_unit": "feet",
        "anchor": "front-center-bottom",
        "preferred_camera": "front-elevation",
    },
}
