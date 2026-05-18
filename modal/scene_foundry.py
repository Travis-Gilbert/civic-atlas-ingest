"""Modal app: civic_atlas_scene_foundry.

Renders a `ReconstructionSpec` into a glTF asset using one of the
eight Blender archetypes from civic-atlas-primitives.

Flow:
  1. Caller (outbox worker, or direct gRPC from Axum) hands the spec
     JSON, the archetype slug, and a target S3 URI.
  2. This app spins up a Modal container with Blender 4.2 LTS, mounts
     the civic-atlas-primitives volume (Blender files + render_spec.py),
     and runs headless Blender against the right archetype.
  3. Result GLB is uploaded to S3 under
     s3://civic-atlas/<tenant>/assets/<spec_id>/v<version>/<content_hash>.glb.
  4. App returns the URI + content_hash; caller writes the
     generated_assets row in PostGIS.

Status: Phase 3 stub. The image build + Blender invocation is wired,
but the actual archetype .blend files don't exist yet in
civic-atlas-primitives, so a render call returns a "phase-3-stub"
error from render_spec.py.

Run:
    modal deploy modal/scene_foundry.py
    modal run modal/scene_foundry.py::render \
        --spec-json @path/to/spec.json \
        --archetype frame-house-with-porch \
        --tenant flint \
        --spec-id spec:carriage-town:2 \
        --spec-version 1

Environment:
    CIVIC_ATLAS_GRPC_URL    Atlas backend (for writing generated_assets)
    SCENE_FOUNDRY_TOKEN     bearer token with write scope on the target tenant
    S3_BUCKET               defaults to civic-atlas
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import modal

# Blender 4.2 LTS in a Debian-based image. The civic-atlas-primitives
# repo is mounted at /opt/civic-atlas-primitives via a Modal volume,
# populated by a separate "primitives_sync" function (TODO).
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        "wget", "xz-utils", "libxi6", "libxxf86vm1", "libxfixes3",
        "libgl1", "libxkbcommon0", "libsm6", "libice6", "libxrender1",
    )
    .run_commands(
        # Pin Blender to 4.2 LTS so archetype hashes stay stable.
        "wget -q https://download.blender.org/release/Blender4.2/blender-4.2.3-linux-x64.tar.xz "
        "-O /tmp/blender.tar.xz",
        "tar -xf /tmp/blender.tar.xz -C /opt",
        "mv /opt/blender-4.2.3-linux-x64 /opt/blender",
        "ln -s /opt/blender/blender /usr/local/bin/blender",
        "rm /tmp/blender.tar.xz",
    )
    .pip_install(
        "boto3>=1.35",
        "grpcio>=1.65",
        "protobuf>=5.27",
        "jsonschema>=4.21",
    )
)

app = modal.App("civic-atlas-scene-foundry", image=image)

PRIMITIVES_VOLUME = modal.Volume.from_name(
    "civic-atlas-primitives", create_if_missing=True
)


@app.function(
    cpu=4,
    memory=8192,
    timeout=60 * 15,
    secrets=[
        modal.Secret.from_name("civic-atlas-scene-foundry"),
        modal.Secret.from_name("civic-atlas-aws"),
    ],
    volumes={"/opt/civic-atlas-primitives": PRIMITIVES_VOLUME},
)
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
        "archetype_hash": "sha256-...",  # from civic-atlas-primitives _hashes.json
      }
    """
    primitives_root = Path("/opt/civic-atlas-primitives")
    archetype_dir = primitives_root / "archetypes" / archetype.replace("-", "_")
    blend_file = archetype_dir / "archetype.blend"
    render_script = primitives_root / "scripts" / "render_spec.py"

    if not blend_file.exists():
        raise RuntimeError(
            f"phase-3-stub: archetype {archetype!r} has no .blend yet. "
            f"Author it in civic-atlas-primitives and re-sync the volume. "
            f"Expected: {blend_file}"
        )
    if not render_script.exists():
        raise RuntimeError(f"missing render script: {render_script}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        spec_path = tmp / "spec.json"
        spec_path.write_text(spec_json)
        out_path = tmp / "out.glb"

        cmd = [
            "blender",
            str(blend_file),
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
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"blender render failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout[-2000:]}\n"
                f"stderr: {result.stderr[-2000:]}"
            )

        if not out_path.exists():
            raise RuntimeError("render succeeded but no GLB written")

        content_hash = "sha256-" + hashlib.sha256(out_path.read_bytes()).hexdigest()

        # Upload to S3
        import boto3
        bucket = os.environ.get("S3_BUCKET", "civic-atlas")
        key = f"{tenant}/assets/{spec_id}/v{spec_version}/{content_hash}.glb"
        s3 = boto3.client("s3")
        with out_path.open("rb") as f:
            s3.upload_fileobj(f, bucket, key, ExtraArgs={"ContentType": "model/gltf-binary"})

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
        }


@app.function(cpu=1, memory=2048, timeout=60 * 10)
def primitives_sync(git_url: str = "https://github.com/Travis-Gilbert/civic-atlas-primitives.git") -> dict[str, Any]:
    """Sync the civic-atlas-primitives repo into the mounted volume.

    Called by an operator (or a periodic cron) when the primitives
    repo updates. Clones the repo, rewrites /opt/civic-atlas-primitives,
    commits the volume.
    """
    target = "/opt/civic-atlas-primitives"
    if os.path.exists(target):
        shutil.rmtree(target)
    subprocess.run(["git", "clone", "--depth", "1", git_url, target], check=True)
    PRIMITIVES_VOLUME.commit()
    return {
        "target": target,
        "git_url": git_url,
        "archetype_count": len(list(Path(target, "archetypes").iterdir())),
    }


@app.local_entrypoint()
def main(spec_path: str = "", archetype: str = "frame-house-with-porch") -> None:
    """Local entrypoint. Reads a spec file and calls render."""
    if not spec_path:
        print("Pass --spec-path <path>")
        return
    spec = Path(spec_path).read_text()
    spec_dict = json.loads(spec)
    result = render.remote(
        spec_json=spec,
        archetype=archetype,
        tenant=spec_dict.get("tenant_context", {}).get("tenant_id", "flint"),
        spec_id=spec_dict.get("spec_id", "unknown"),
        spec_version=spec_dict.get("version", 1),
    )
    print(result)
