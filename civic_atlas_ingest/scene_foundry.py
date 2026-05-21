"""Ray task: civic_atlas_scene_foundry.

Renders a `ReconstructionSpec` into a glTF asset using one of the
eight Blender archetypes in this repo's `primitives/` subdir.

Flow:
  1. Caller (outbox worker, or direct gRPC from Axum) hands the spec
     JSON, the archetype slug, and a target S3 URI.
  2. A RunPod Ray worker with Blender 4.2 LTS installed reads the
     `primitives/` directory from the submitted working directory or a synced
     mount.
  3. Runs headless Blender against the right archetype's .blend file when
     present, otherwise uses the checked-in procedural archetype builder.
  4. Result GLB is uploaded to S3 under
     s3://civic-atlas/<tenant>/assets/<spec_id>/v<version>/<content_hash>.glb.
  5. App returns the URI + content_hash; caller writes the
     generated_assets row in PostGIS.

Status: XRL-C-001 runtime path. Local developer machines can validate the
renderer contract without binary `.blend` files because `render_spec.py`
builds the eight archetypes procedurally inside Blender. Hand-authored
`.blend` files can still override the procedural path later.

Run:
    cd civic-atlas-ingest
    ray job submit --working-dir . -- python -m civic_atlas_ingest.scene_foundry \\
        --spec-json @path/to/spec.json \\
        --archetype frame-house-with-porch \\
        --tenant flint \\
        --spec-id spec:carriage-town:2 \\
        --spec-version 1

Environment:
    CIVIC_ATLAS_GRPC_URL    Atlas backend (for writing generated_assets)
    SCENE_FOUNDRY_TOKEN     bearer token with write scope on the target tenant
    S3_BUCKET               defaults to civic-atlas
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .runtime import ensure_ray_initialized, ray


@ray.remote(num_cpus=4, num_gpus=1, memory=8 * 1024 * 1024 * 1024)
def render(
    spec_json: str,
    archetype: str,
    tenant: str,
    spec_id: str,
    spec_version: int,
) -> dict[str, Any]:
    """Render one spec into a GLB and upload to S3.

    Returns:
      {
        "uri": "s3://civic-atlas/<tenant>/assets/.../<hash>.glb",
        "content_hash": "sha256-...",
        "archetype": "...",
        "archetype_hash": "sha256-...",  # from primitives/archetypes/_hashes.json
        "openbim_uri": "s3://...",
      }
    """
    primitives_root = Path(os.environ.get("CIVIC_ATLAS_PRIMITIVES_ROOT", "primitives"))
    archetype_dir = primitives_root / "archetypes" / archetype.replace("-", "_")
    blend_file = archetype_dir / "archetype.blend"
    render_script = primitives_root / "scripts" / "render_spec.py"

    if not render_script.exists():
        raise RuntimeError(f"missing render script: {render_script}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        spec_path = tmp / "spec.json"
        spec_path.write_text(spec_json)
        out_path = tmp / "out.glb"
        ifc_path = tmp / "out.ifc"

        cmd = ["blender"]
        if blend_file.exists():
            cmd.append(str(blend_file))
        cmd.extend(
            [
                "--background",
                "--python",
                str(render_script),
                "--",
                "--archetype",
                archetype,
                "--spec",
                str(spec_path),
                "--out",
                str(out_path),
                "--ifc-out",
                str(ifc_path),
            ]
        )

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
        if result.returncode != 0:
            raise RuntimeError(
                f"blender render failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout[-2000:]}\n"
                f"stderr: {result.stderr[-2000:]}"
            )

        if not out_path.exists():
            raise RuntimeError("render succeeded but no GLB written")

        content_hash = "sha256-" + hashlib.sha256(out_path.read_bytes()).hexdigest()
        ifc_hash = (
            "sha256-" + hashlib.sha256(ifc_path.read_bytes()).hexdigest()
            if ifc_path.exists()
            else None
        )

        # Upload to S3
        import boto3
        bucket = os.environ.get("S3_BUCKET", "civic-atlas")
        key = f"{tenant}/assets/{spec_id}/v{spec_version}/{content_hash}.glb"
        s3 = boto3.client("s3")
        with out_path.open("rb") as f:
            s3.upload_fileobj(f, bucket, key, ExtraArgs={"ContentType": "model/gltf-binary"})
        ifc_uri = None
        if ifc_path.exists() and ifc_hash:
            ifc_key = f"{tenant}/assets/{spec_id}/v{spec_version}/{ifc_hash}.ifc"
            with ifc_path.open("rb") as f:
                s3.upload_fileobj(f, bucket, ifc_key, ExtraArgs={"ContentType": "model/ifc"})
            ifc_uri = f"s3://{bucket}/{ifc_key}"

        uri = f"s3://{bucket}/{key}"

        archetype_hashes_path = primitives_root / "archetypes" / "_hashes.json"
        archetype_hash = None
        if archetype_hashes_path.exists():
            archetype_hash = json.loads(archetype_hashes_path.read_text()).get(archetype)

        return {
            "uri": uri,
            "content_hash": content_hash,
            "archetype": archetype,
            "archetype_hash": archetype_hash,
            "openbim_uri": ifc_uri,
            "openbim_hash": ifc_hash,
        }


def _spec_arg_to_json(spec_arg: str) -> str:
    if spec_arg.startswith("@"):
        return Path(spec_arg[1:]).read_text()
    candidate = Path(spec_arg)
    if candidate.exists():
        return candidate.read_text()
    return spec_arg


def main(
    spec_json: str = "",
    archetype: str = "frame-house-with-porch",
    tenant: str = "",
    spec_id: str = "",
    spec_version: int = 0,
) -> None:
    """Local entrypoint. Reads a spec file and calls render."""
    if not spec_json:
        print("Pass --spec-json @path/to/spec.json")
        return
    spec = _spec_arg_to_json(spec_json)
    spec_dict = json.loads(spec)
    tenant = tenant or spec_dict.get("tenant_context", {}).get("tenant_id", "flint")
    spec_id = spec_id or spec_dict.get("spec_id", "unknown")
    spec_version = spec_version or spec_dict.get("spec_version", spec_dict.get("version", 1))
    ensure_ray_initialized()
    result = ray.get(
        render.remote(
            spec_json=spec,
            archetype=archetype,
            tenant=tenant,
            spec_id=spec_id,
            spec_version=spec_version,
        )
    )
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render a ReconstructionSpec through Ray")
    parser.add_argument("--spec-json", default="")
    parser.add_argument("--archetype", default="frame-house-with-porch")
    parser.add_argument("--tenant", default="")
    parser.add_argument("--spec-id", default="")
    parser.add_argument("--spec-version", type=int, default=0)
    args = parser.parse_args()
    main(
        spec_json=args.spec_json,
        archetype=args.archetype,
        tenant=args.tenant,
        spec_id=args.spec_id,
        spec_version=args.spec_version,
    )
