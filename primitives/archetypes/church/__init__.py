"""Archetype: church (nave + tower + optional transept).

Tower height comes from `mass.height.max` when the spec includes a
tower; transepts are toggled via an ornament entry with
kind="transept". Spire is optional via kind="spire".
"""

from __future__ import annotations

MANIFEST = {
    "slug": "church",
    "blend_file": "archetype.blend",
    "description": "Church with nave, optional tower, transept, and spire",
    "spec_fields_used": [
        "mass.height.max",
        "mass.width.max",
        "mass.depth.max",
        "facades[0].material",
        "facades[0].opening_grids[*].opening_type",
        "roof.form",
        "roof.material",
        "roof.pitch_degrees",
        "ornaments[*].kind",
        "ornaments[*].location",
        "ornaments[*].material",
    ],
    "material_slots": [
        {"slot_name": "Wall", "spec_field_path": "facades[0].material",
         "fallback_material": "Limestone"},
        {"slot_name": "Roof", "spec_field_path": "roof.material",
         "fallback_material": "SlateTile"},
        {"slot_name": "TowerCap", "spec_field_path": "ornaments[kind=spire].material",
         "fallback_material": "CopperPatina"},
        {"slot_name": "StainedGlass",
         "spec_field_path": "facades[0].opening_grids[0].opening_type",
         "fallback_material": "StainedGlassPanel"},
    ],
    "geometry_nodes_group_name": "Church",
    "render_hints": {
        "scale_unit": "feet",
        "anchor": "front-center-bottom",
        "preferred_camera": "three-quarter-front",
    },
}
