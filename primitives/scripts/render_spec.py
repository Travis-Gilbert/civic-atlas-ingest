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
.blend files are authored and the Scene Foundry Modal app calls in.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import bpy  # type: ignore[import-not-found]
except ImportError:
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
    """Phase 3 stub. Real implementation will:

    1. Locate the geometry-nodes group named per
       archetypes/<archetype>/__init__.py::MANIFEST.geometry_nodes_group_name.
    2. For each spec field listed in MANIFEST.spec_fields_used, write
       the value to the matching input socket on the modifier.
    3. For each material slot in MANIFEST.material_slots, look up the
       value at spec_field_path and swap the slot to the matching
       library material (or fall back to fallback_material).
    """
    _ = (archetype, spec)
    raise NotImplementedError(
        "Phase 3 stub: real geometry-nodes wiring lands once Blender "
        "files are authored. The Scene Foundry Modal app will call this "
        "with the spec, archetype slug, and an out path."
    )


def export_glb(out_path: Path) -> None:
    """Phase 3 stub. Real export uses bpy.ops.export_scene.gltf with
    file_format='GLB' and the active mesh as the export set."""
    _ = out_path
    raise NotImplementedError("Phase 3 stub: GLB export TBD")


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
    except NotImplementedError as exc:
        print(f"phase-3-stub: {exc}", file=sys.stderr)
        sys.exit(4)


if __name__ == "__main__":
    main()
