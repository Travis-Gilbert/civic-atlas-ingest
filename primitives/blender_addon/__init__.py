"""civic-atlas-primitives Blender addon.

When installed in Blender, this addon registers the geometry-nodes
groups for each archetype and the Spec-modifier panel that fills
input sockets from a spec JSON. Local-dev only; the Scene Foundry
Modal worker calls scripts/render_spec.py directly without this
addon.

Phase 3 stub: register hook is a no-op until the geometry-nodes
groups are authored.
"""

from __future__ import annotations

bl_info = {
    "name": "Civic Atlas Primitives",
    "author": "Travis Gilbert",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Civic Atlas",
    "description": "Geometry-nodes archetypes for Civic Atlas Scene Foundry",
    "category": "Object",
}


def register() -> None:
    """No-op for Phase 3. Real register adds Spec modifier UI."""
    pass


def unregister() -> None:
    pass
