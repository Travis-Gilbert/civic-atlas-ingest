"""Modal app: serve building head inference.

Status: skeleton. Real inference loop pending finalization of the
ReconstructionSpec proto and the trained model artifact.

The Atlas backend's `GenerateSpecPriors(parcel_id, time_slice)` calls
this Modal endpoint. Flow:

  1. Backend resolves parcel_id -> block_subgraph via
     SpacetimeAtlasService.GetBlockSubgraph (RustyRed).
  2. Backend calls TheseusBridge.GetBatchSpacetimeEmbeddings on the
     subgraph's node_ids.
  3. Backend POSTs the assembled tensor to this Modal endpoint.
  4. This endpoint loads the production model (or staging if flagged),
     runs the CivicPairformerBuildingHead, decodes per-part field
     distributions.
  5. Returns a ReconstructionSpec with every populated field carrying
     `from_gnn_prior=true` and `gnn_version=<model version>`.

The promotion ladder is staging -> production with manual confirm.
This endpoint reads the slot pointer from S3 metadata, not from a
hard-coded path, so a promote operation flips slots without redeploy.

Run:
    modal deploy modal/building_head_infer.py
    modal run modal/building_head_infer.py::predict \
        --tensor-uri s3://civic-atlas/staging/predict-1.npz

Environment:
    MODEL_SLOT          'staging' or 'production' (default production)
    S3_BUCKET           defaults to civic-atlas
"""

from __future__ import annotations

import os
from typing import Any, Literal

import modal

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch>=2.4",
        "torch-geometric>=2.5",
        "numpy>=1.26",
        "boto3>=1.35",
        "fastapi[standard]>=0.115",
    )
)

app = modal.App("civic-atlas-building-head-infer", image=image)


ModelSlot = Literal["staging", "production"]


@app.function(
    gpu="T4",
    timeout=60,
    cpu=2,
    memory=8192,
    secrets=[modal.Secret.from_name("civic-atlas-aws")],
    keep_warm=1,
)
@modal.web_endpoint(method="POST", label="building-head-predict")
def predict(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the building head over a serialized block subgraph tensor.

    Payload schema (will be locked to a proto once ReconstructionSpec
    is final):
      {
        "block_subgraph_tensor_uri": "s3://...",   # serialized tensor
        "model_slot": "production",                 # or "staging"
        "tenant_id": "flint",                       # for audit only
      }

    Response schema:
      {
        "reconstruction_spec_json": "...",          # encoded ReconstructionSpec
        "model_version": "v0.3.1",
        "produced_at_ms": 1715000000000,
      }
    """
    raise NotImplementedError(
        "Phase 6 stub. Implementation lands after:\n"
        "  - ReconstructionSpec is final\n"
        "  - A trained model artifact exists in S3\n"
        f"payload keys={sorted(payload.keys())}"
    )


@app.function(
    cpu=1,
    memory=2048,
    secrets=[modal.Secret.from_name("civic-atlas-aws")],
)
def health(slot: ModelSlot = "production") -> dict[str, Any]:
    """Check that a model slot has a loadable artifact."""
    return {
        "slot": slot,
        "status": "stub",
        "note": "Phase 6 inference is a stub. Health check not yet wired.",
    }


@app.local_entrypoint()
def main(tensor_uri: str = "") -> None:
    """Local entrypoint for `modal run`."""
    if not tensor_uri:
        print("Pass --tensor-uri s3://...")
        return
    result = predict.remote(
        payload={
            "block_subgraph_tensor_uri": tensor_uri,
            "model_slot": os.environ.get("MODEL_SLOT", "production"),
            "tenant_id": "flint",
        }
    )
    print(result)


_BUCKET = os.environ.get("S3_BUCKET", "civic-atlas")
