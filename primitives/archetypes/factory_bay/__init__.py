"""Archetype: industrial factory bay with clerestory.

For Flint's auto-era industrial buildings: long single-story bays
with sawtooth or shed clerestory roofs, structural brick or
corrugated metal walls, regular pilaster rhythm. Mass.depth drives
bay count.
"""

from __future__ import annotations

MANIFEST = {
    "slug": "factory-bay",
    "blend_file": "archetype.blend",
    "description": "Industrial factory bay, single story, sawtooth or shed clerestory",
    "spec_fields_used": [
        "mass.height.max",
        "mass.width.max",
        "mass.depth.max",
        "facades[0].material",
        "facades[0].opening_grids[0].bay_count",
        "facades[0].opening_grids[0].rhythm",
        "roof.form",
        "roof.material",
        "ornaments[*].kind",
    ],
    "material_slots": [
        {"slot_name": "Wall", "spec_field_path": "facades[0].material",
         "fallback_material": "IndustrialBrick"},
        {"slot_name": "WindowFrame", "spec_field_path": "facades[0].opening_grids[0].opening_type",
         "fallback_material": "SteelSashWindow"},
        {"slot_name": "Roof", "spec_field_path": "roof.material",
         "fallback_material": "BuildupRoofing"},
    ],
    "geometry_nodes_group_name": "FactoryBay",
    "render_hints": {
        "scale_unit": "feet",
        "anchor": "front-center-bottom",
        "preferred_camera": "front-elevation",
    },
}
