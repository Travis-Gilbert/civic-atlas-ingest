"""Civic Atlas Scene Foundry archetypes registry.

Each subpackage exports a `MANIFEST` dict describing how to render
a `ReconstructionSpec` using that archetype's Blender file. The
Scene Foundry imports `ARCHETYPES` to dispatch by slug.
"""

from __future__ import annotations

from . import (
    church,
    commercial_brick_two_story,
    factory_bay,
    frame_house_with_porch,
    gas_station,
    mixed_use_storefront,
    school,
    warehouse,
)

ARCHETYPES = {
    "commercial-brick-two-story": commercial_brick_two_story.MANIFEST,
    "frame-house-with-porch": frame_house_with_porch.MANIFEST,
    "factory-bay": factory_bay.MANIFEST,
    "warehouse": warehouse.MANIFEST,
    "church": church.MANIFEST,
    "school": school.MANIFEST,
    "gas-station": gas_station.MANIFEST,
    "mixed-use-storefront": mixed_use_storefront.MANIFEST,
}
