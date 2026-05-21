"""Blender entrypoint: render one ReconstructionSpec into a glTF asset.

Invoked under headless Blender:

  blender archetypes/<slug>/archetype.blend \
    --background \
    --python scripts/render_spec.py -- \
    --archetype <slug> \
    --spec spec.json \
    --out out.glb

This script lives outside of Blender's Python path; it sets up sys.path
and bpy is only resolved when running inside Blender. When invoked
outside Blender (e.g. by `pytest`) the script exits with a clear
message rather than ImportError.

Status: Phase 3 stub. The render pipeline is sketched below; the
real geometry-node modification + GLB export lands once the
.blend files are authored and the Scene Foundry Ray task calls in.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

if importlib.util.find_spec("bpy") is None:
    print(
        "render_spec.py must run inside Blender. "
        "Try: blender archetypes/<slug>/archetype.blend --background "
        "--python scripts/render_spec.py -- --archetype <slug> "
        "--spec spec.json --out out.glb",
        file=sys.stderr,
    )
    sys.exit(2)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a ReconstructionSpec into glTF")
    parser.add_argument("--archetype", required=True, help="archetype slug")
    parser.add_argument("--spec", required=True, help="path to spec JSON")
    parser.add_argument("--out", required=True, help="output glTF path")
    parser.add_argument("--validate-only", action="store_true",
                        help="only validate spec; skip render")
    parser.add_argument("--ifc-out", default="", help="optional IFC sidecar output path")
    return parser.parse_args(argv)


def split_argv() -> list[str]:
    """Blender swallows arguments before '--'; everything after belongs to us."""
    if "--" in sys.argv:
        idx = sys.argv.index("--")
        return sys.argv[idx + 1:]
    return []


def load_spec(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def apply_spec_to_archetype(archetype: str, spec: dict) -> None:
    """Create a deterministic procedural archetype scene from a spec."""
    import bpy

    manifest = load_manifest(archetype)
    reset_scene()
    install_materials(manifest, spec)
    builders = {
        "commercial-brick-two-story": build_commercial_brick,
        "frame-house-with-porch": build_frame_house,
        "factory-bay": build_factory_bay,
        "warehouse": build_warehouse,
        "church": build_church,
        "school": build_school,
        "gas-station": build_gas_station,
        "mixed-use-storefront": build_mixed_use_storefront,
    }
    if archetype not in builders:
        raise ValueError(f"unknown archetype: {archetype}")
    builders[archetype](spec)

    bpy.context.scene["civic_atlas_archetype"] = archetype
    bpy.context.scene["civic_atlas_spec_id"] = str(spec.get("spec_id", "unknown"))
    bpy.context.scene.render.engine = "CYCLES"
    bpy.context.scene.unit_settings.system = "IMPERIAL"
    add_camera_and_light()


def export_glb(out_path: Path) -> None:
    """Export the active scene as a GLB."""
    import bpy

    out_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(out_path), export_format="GLB")


def load_manifest(archetype: str) -> dict:
    primitives_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(primitives_root))
    from archetypes import ARCHETYPES

    try:
        return ARCHETYPES[archetype]
    except KeyError as exc:
        raise ValueError(f"unknown archetype: {archetype}") from exc


def reset_scene() -> None:
    import bpy

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def install_materials(manifest: dict, spec: dict) -> None:
    for slot in manifest.get("material_slots", []):
        material_name = str(slot.get("fallback_material") or slot.get("slot_name"))
        color = material_color(material_name)
        make_material(material_name, color)
    for name, color in {
        "Glass": (0.5, 0.75, 0.9, 0.45),
        "DarkGlass": (0.08, 0.12, 0.14, 0.7),
        "Concrete": (0.55, 0.55, 0.5, 1),
        "Metal": (0.42, 0.42, 0.42, 1),
        "BrickTrim": (0.55, 0.18, 0.11, 1),
        "PorchWood": (0.82, 0.72, 0.55, 1),
    }.items():
        make_material(name, color)
    _ = spec


def make_material(name: str, color: tuple[float, float, float, float]) -> Any:
    import bpy

    if name in bpy.data.materials:
        return bpy.data.materials[name]
    material = bpy.data.materials.new(name)
    material.diffuse_color = color
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = 0.72
        if color[3] < 1:
            bsdf.inputs["Alpha"].default_value = color[3]
            material.blend_method = "BLEND"
    return material


def material_color(name: str) -> tuple[float, float, float, float]:
    key = name.lower()
    if "brick" in key:
        return (0.58, 0.18, 0.11, 1)
    if "limestone" in key or "stone" in key:
        return (0.72, 0.69, 0.62, 1)
    if "slate" in key or "roof" in key:
        return (0.18, 0.2, 0.22, 1)
    if "wood" in key or "clapboard" in key:
        return (0.78, 0.68, 0.52, 1)
    if "glass" in key:
        return (0.45, 0.75, 0.9, 0.5)
    if "copper" in key:
        return (0.32, 0.65, 0.55, 1)
    if "steel" in key or "metal" in key:
        return (0.42, 0.42, 0.42, 1)
    return (0.68, 0.66, 0.58, 1)


def build_commercial_brick(spec: dict) -> None:
    w, d, h = dims(spec, default=(28, 60, 26))
    box("main brick mass", (0, 0, h / 2), (w, d, h), "GenericRedBrick")
    box("storefront glazing", (0, -d / 2 - 0.03, 5), (w * 0.82, 0.15, 7), "Glass")
    add_window_grid(w, d, h, floors=1, bays=4, z_base=15)
    box("parapet coping", (0, -d / 2, h + 1.2), (w * 1.04, 0.6, 2.4), "ParapetCoping")


def build_frame_house(spec: dict) -> None:
    w, d, h = dims(spec, default=(24, 34, 20))
    box("wood frame mass", (0, 0, h / 2), (w, d, h), "WoodClapboard")
    gable_roof(w, d, h, material="AsphaltShingle")
    box("front porch deck", (0, -d / 2 - 4, 2), (w * 0.78, 8, 4), "PorchWood")
    for x in (-w * 0.28, w * 0.28):
        box("porch post", (x, -d / 2 - 7, 6), (0.8, 0.8, 8), "TurnedWoodPost")
    add_window_grid(w, d, h, floors=2, bays=3, z_base=7)


def build_factory_bay(spec: dict) -> None:
    w, d, h = dims(spec, default=(80, 160, 22))
    box("factory bay mass", (0, 0, h / 2), (w, d, h), "IndustrialBrick")
    for index in range(4):
        y = -d / 2 + (index + 0.5) * d / 4
        box("sawtooth clerestory", (0, y, h + 3), (w, d / 10, 6), "BuildupRoofing")
    add_window_grid(w, d, h, floors=1, bays=8, z_base=11, material="SteelSashWindow")


def build_warehouse(spec: dict) -> None:
    w, d, h = dims(spec, default=(70, 110, 24))
    box("warehouse mass", (0, 0, h / 2), (w, d, h), "WarehouseBrick")
    box("loading door", (-w * 0.25, -d / 2 - 0.04, 6), (10, 0.2, 10), "SteelOverheadDoor")
    box("loading door", (w * 0.25, -d / 2 - 0.04, 6), (10, 0.2, 10), "SteelOverheadDoor")
    flat_roof(w, d, h)


def build_church(spec: dict) -> None:
    w, d, h = dims(spec, default=(42, 92, 34))
    box("nave", (0, 0, h / 2), (w, d, h), "Limestone")
    gable_roof(w, d, h, material="SlateTile")
    tower_h = h * 1.45
    box(
        "front tower",
        (-w * 0.28, -d / 2 - 2, tower_h / 2),
        (w * 0.28, w * 0.28, tower_h),
        "Limestone",
    )
    box(
        "spire",
        (-w * 0.28, -d / 2 - 2, tower_h + 5),
        (w * 0.2, w * 0.2, 10),
        "CopperPatina",
    )
    add_window_grid(w, d, h, floors=1, bays=3, z_base=14, material="StainedGlassPanel")


def build_school(spec: dict) -> None:
    w, d, h = dims(spec, default=(95, 68, 34))
    box("school main block", (0, 0, h / 2), (w, d, h), "InstitutionalBrick")
    box("central entry", (0, -d / 2 - 2, h / 2), (w * 0.2, 4, h * 1.15), "Limestone")
    add_window_grid(w, d, h, floors=3, bays=8, z_base=8)
    flat_roof(w, d, h)


def build_gas_station(spec: dict) -> None:
    w, d, h = dims(spec, default=(48, 38, 15))
    box("service bay", (w * 0.18, 0, h / 2), (w * 0.62, d, h), "PorcelainEnamel")
    box("canopy", (-w * 0.24, -d * 0.1, h + 2), (w * 0.7, d * 0.85, 3), "BuildupRoofing")
    for x in (-w * 0.38, -w * 0.08):
        box("pump island", (x, -d * 0.2, 2), (3, 6, 4), "PaintedSteel")
    box("service door", (w * 0.28, -d / 2 - 0.03, 5), (10, 0.2, 8), "Metal")


def build_mixed_use_storefront(spec: dict) -> None:
    w, d, h = dims(spec, default=(34, 72, 42))
    box("upper mixed-use mass", (0, 0, h / 2), (w, d, h), "FlemishBondBrick")
    box(
        "retail storefront",
        (0, -d / 2 - 0.04, 6),
        (w * 0.88, 0.2, 9),
        "TwentiethCenturyStorefront",
    )
    box("canvas awning", (0, -d / 2 - 1.2, 11), (w * 0.9, 3, 1), "CanvasAwning")
    add_window_grid(w, d, h, floors=3, bays=4, z_base=18)
    box("cornice", (0, -d / 2, h + 1), (w * 1.03, 0.8, 2), "StampedMetal")


def dims(spec: dict, *, default: tuple[float, float, float]) -> tuple[float, float, float]:
    mass = spec.get("mass") if isinstance(spec.get("mass"), dict) else {}
    width = number_at(mass, "width.max") or number_at(mass, "width") or default[0]
    depth = number_at(mass, "depth.max") or number_at(mass, "depth") or default[1]
    height = number_at(mass, "height.max") or number_at(mass, "height") or default[2]
    return float(width), float(depth), float(height)


def number_at(value: dict, path: str) -> float | None:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    try:
        return float(current)
    except (TypeError, ValueError):
        return None


def box(name: str, location: tuple[float, float, float], size: tuple[float, float, float],
        material: str) -> None:
    import bpy

    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(make_material(material, material_color(material)))


def add_window_grid(
    w: float,
    d: float,
    h: float,
    *,
    floors: int,
    bays: int,
    z_base: float,
    material: str = "DarkGlass",
) -> None:
    floor_gap = max(5.5, (h - z_base - 3) / max(floors, 1))
    bay_gap = w / (bays + 1)
    for floor in range(floors):
        for bay in range(bays):
            x = -w / 2 + bay_gap * (bay + 1)
            z = z_base + floor * floor_gap
            box("window", (x, -d / 2 - 0.06, z), (bay_gap * 0.45, 0.12, 3.8), material)


def gable_roof(w: float, d: float, h: float, *, material: str) -> None:
    box("gable roof", (0, 0, h + 2.2), (w * 1.08, d * 1.06, 4.4), material)


def flat_roof(w: float, d: float, h: float) -> None:
    box("flat roof", (0, 0, h + 0.6), (w * 1.03, d * 1.03, 1.2), "BuildupRoofing")


def add_camera_and_light() -> None:
    import bpy

    bpy.ops.object.light_add(type="AREA", location=(30, -55, 70))
    light = bpy.context.object
    light.name = "softbox"
    light.data.energy = 600
    light.data.size = 35
    bpy.ops.object.camera_add(location=(72, -92, 52), rotation=(1.1, 0, 0.68))
    bpy.context.scene.camera = bpy.context.object


def main() -> None:
    args = parse_args(split_argv())
    spec = load_spec(Path(args.spec))

    if args.validate_only:
        if "spec_id" not in spec:
            print("spec missing spec_id", file=sys.stderr)
            sys.exit(3)
        print(f"ok: validate-only run for spec_id={spec['spec_id']}")
        return

    try:
        apply_spec_to_archetype(args.archetype, spec)
        export_glb(Path(args.out))
        if args.ifc_out:
            primitives_root = Path(__file__).resolve().parent.parent
            sys.path.insert(0, str(primitives_root))
            from openbim import write_ifc

            write_ifc(Path(args.ifc_out), archetype=args.archetype, spec=spec)
    except Exception as exc:
        print(f"render failed: {exc}", file=sys.stderr)
        sys.exit(4)


if __name__ == "__main__":
    main()
