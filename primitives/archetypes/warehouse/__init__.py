"""Archetype: rectangular warehouse, 1-2 stories.

Loading-dock entries, minimal windows, low pitched or flat roof.
Generally less ornamented than factory bays.
"""

from __future__ import annotations

MANIFEST = {
    "slug": "warehouse",
    "blend_file": "archetype.blend",
    "description": "Warehouse, single or two-story, with loading docks",
    "spec_fields_used": [
        "mass.height.max",
        "mass.width.max",
        "mass.depth.max",
        "mass.story_count",
        "facades[0].material",
        "ground_floor.entry_location",
        "roof.form",
        "roof.material",
    ],
    "material_slots": [
        {"slot_name": "Wall", "spec_field_path": "facades[0].material",
         "fallback_material": "WarehouseBrick"},
        {"slot_name": "Roof", "spec_field_path": "roof.material",
         "fallback_material": "BuildupRoofing"},
        {"slot_name": "LoadingDoor", "spec_field_path": "ground_floor.entry_location",
         "fallback_material": "SteelOverheadDoor"},
    ],
    "geometry_nodes_group_name": "Warehouse",
    "render_hints": {
        "scale_unit": "feet",
        "anchor": "front-center-bottom",
        "preferred_camera": "front-elevation",
    },
}
