"""Archetype: two-story brick commercial main-street building.

Typical Carriage Town / Saginaw / Buffalo Rust-Belt morphology:
parapet-top facade, cornice, recessed entry on ground floor, repeating
double-hung windows on upper floor. Geometry-nodes group reads facade
bay count, story heights, and roof parapet height from the spec.
"""

from __future__ import annotations

MANIFEST = {
    "slug": "commercial-brick-two-story",
    "blend_file": "archetype.blend",
    "description": "Two-story brick commercial building with parapet and storefront",
    "spec_fields_used": [
        "mass.height.max",
        "mass.width.max",
        "mass.depth.max",
        "mass.story_count",
        "facades[0].material",
        "facades[0].color",
        "facades[0].opening_grids[0].bay_count",
        "facades[0].opening_grids[0].rhythm",
        "ground_floor.use_type",
        "ground_floor.storefront_type",
        "ground_floor.has_awning",
        "roof.form",
        "roof.material",
        "ornaments[*].kind",
        "ornaments[*].location",
    ],
    "material_slots": [
        {"slot_name": "FacadeBrick", "spec_field_path": "facades[0].material",
         "fallback_material": "GenericRedBrick"},
        {"slot_name": "FacadeAccent", "spec_field_path": "facades[0].color",
         "fallback_material": "BrickTrim"},
        {"slot_name": "Parapet", "spec_field_path": "roof.material",
         "fallback_material": "ParapetCoping"},
        {"slot_name": "Storefront", "spec_field_path": "ground_floor.storefront_type",
         "fallback_material": "StorefrontGlazing"},
    ],
    "geometry_nodes_group_name": "CommercialBrickTwoStory",
    "render_hints": {
        "scale_unit": "feet",
        "anchor": "front-center-bottom",
        "preferred_camera": "south-elevation",
    },
}
