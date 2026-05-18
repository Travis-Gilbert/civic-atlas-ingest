"""Archetype: wood-frame house with a front porch.

Covers Queen Anne, Folk Victorian, and Italianate house variants
common in Carriage Town and other late-19th / early-20th-century
Rust-Belt neighborhoods. Porch type (column count, roof) is driven
by ornaments[] entries with kind="porch".
"""

from __future__ import annotations

MANIFEST = {
    "slug": "frame-house-with-porch",
    "blend_file": "archetype.blend",
    "description": "Wood-frame residential building with front porch, 1-2.5 stories",
    "spec_fields_used": [
        "mass.height.max",
        "mass.width.max",
        "mass.depth.max",
        "mass.story_count",
        "facades[0].material",
        "facades[0].color",
        "facades[0].opening_grids[0].bay_count",
        "facades[0].opening_grids[0].floor_count",
        "facades[0].opening_grids[0].opening_type",
        "ground_floor.entry_location",
        "roof.form",
        "roof.material",
        "roof.pitch_degrees",
        "ornaments[*].kind",
        "ornaments[*].location",
        "ornaments[*].material",
    ],
    "material_slots": [
        {"slot_name": "Siding", "spec_field_path": "facades[0].material",
         "fallback_material": "WoodClapboard"},
        {"slot_name": "SidingColor", "spec_field_path": "facades[0].color",
         "fallback_material": "PaintCream"},
        {"slot_name": "Roof", "spec_field_path": "roof.material",
         "fallback_material": "AsphaltShingle"},
        {"slot_name": "PorchPosts", "spec_field_path": "ornaments[kind=porch].material",
         "fallback_material": "TurnedWoodPost"},
    ],
    "geometry_nodes_group_name": "FrameHouseWithPorch",
    "render_hints": {
        "scale_unit": "feet",
        "anchor": "front-center-bottom",
        "preferred_camera": "three-quarter-front",
    },
}
