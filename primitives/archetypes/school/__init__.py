"""Archetype: school (E-plan or H-plan with central entry).

The plan shape comes from `mass.attributes.plan_shape` (one of "E",
"H", "I", "L"). Story count drives the elevation rhythm; the central
entry tower is keyed off `ground_floor.entry_location`.
"""

from __future__ import annotations

MANIFEST = {
    "slug": "school",
    "blend_file": "archetype.blend",
    "description": "School building, E- or H-plan, central entrance, brick",
    "spec_fields_used": [
        "mass.height.max",
        "mass.width.max",
        "mass.depth.max",
        "mass.story_count",
        "mass.attributes",
        "facades[0].material",
        "facades[0].opening_grids[0].bay_count",
        "facades[0].opening_grids[0].floor_count",
        "ground_floor.entry_location",
        "roof.form",
        "roof.material",
        "ornaments[*].kind",
    ],
    "material_slots": [
        {"slot_name": "Wall", "spec_field_path": "facades[0].material",
         "fallback_material": "InstitutionalBrick"},
        {"slot_name": "Trim", "spec_field_path": "ornaments[kind=stringcourse].material",
         "fallback_material": "Limestone"},
        {"slot_name": "Roof", "spec_field_path": "roof.material",
         "fallback_material": "SlateTile"},
    ],
    "geometry_nodes_group_name": "School",
    "render_hints": {
        "scale_unit": "feet",
        "anchor": "front-center-bottom",
        "preferred_camera": "front-elevation",
    },
}
