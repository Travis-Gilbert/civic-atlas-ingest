"""Archetype: mixed-use, retail ground floor + residential upper floors.

Three-to-four story Rust-Belt main-street typology. Ground floor uses
`storefront_type` and `has_awning`; upper floors use the residential
opening-grid rhythm.
"""

from __future__ import annotations

MANIFEST = {
    "slug": "mixed-use-storefront",
    "blend_file": "archetype.blend",
    "description": "Retail ground floor + residential upper floors, 2-4 stories",
    "spec_fields_used": [
        "mass.height.max",
        "mass.width.max",
        "mass.depth.max",
        "mass.story_count",
        "facades[0].material",
        "facades[0].color",
        "facades[0].opening_grids[0].bay_count",
        "facades[0].opening_grids[0].floor_count",
        "facades[0].opening_grids[0].rhythm",
        "ground_floor.use_type",
        "ground_floor.storefront_type",
        "ground_floor.has_awning",
        "roof.form",
        "roof.material",
        "ornaments[*].kind",
    ],
    "material_slots": [
        {"slot_name": "Upper", "spec_field_path": "facades[0].material",
         "fallback_material": "FlemishBondBrick"},
        {"slot_name": "Storefront",
         "spec_field_path": "ground_floor.storefront_type",
         "fallback_material": "TwentiethCenturyStorefront"},
        {"slot_name": "Cornice", "spec_field_path": "ornaments[kind=cornice].material",
         "fallback_material": "StampedMetal"},
        {"slot_name": "Awning", "spec_field_path": "ground_floor.has_awning",
         "fallback_material": "CanvasAwning"},
    ],
    "geometry_nodes_group_name": "MixedUseStorefront",
    "render_hints": {
        "scale_unit": "feet",
        "anchor": "front-center-bottom",
        "preferred_camera": "south-elevation",
    },
}
