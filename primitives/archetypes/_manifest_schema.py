"""Shared manifest schema for archetype descriptors.

Each archetype's `MANIFEST` is validated against this schema before
the Scene Foundry hands the spec to Blender. Keeps the surface
explicit.
"""

from __future__ import annotations

from typing import TypedDict


class MaterialSlot(TypedDict):
    """One material slot the renderer fills from the spec.

    `slot_name` is the Blender material-slot name. `spec_field_path`
    is a JSON-pointer-ish path into the spec, e.g.
    "facades[0].material". `fallback_material` is the material name
    used when the spec leaves the field empty.
    """

    slot_name: str
    spec_field_path: str
    fallback_material: str


class Manifest(TypedDict):
    slug: str
    blend_file: str  # path relative to archetype dir, e.g. "archetype.blend"
    description: str
    spec_fields_used: list[str]
    material_slots: list[MaterialSlot]
    geometry_nodes_group_name: str
    render_hints: dict[str, str]


def validate(manifest: Manifest) -> None:
    """Light validation — full jsonschema validation happens server-side."""
    required = {
        "slug",
        "blend_file",
        "description",
        "spec_fields_used",
        "material_slots",
        "geometry_nodes_group_name",
    }
    missing = required - manifest.keys()
    if missing:
        raise ValueError(f"manifest missing keys: {missing}")
