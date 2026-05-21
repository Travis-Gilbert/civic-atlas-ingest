"""Ray Serve deployment: serve building head inference.

Status: skeleton. Real inference loop pending finalization of the
ReconstructionSpec proto and the trained model artifact.

The Atlas backend's `GenerateSpecPriors(parcel_id, time_slice)` calls
this Ray Serve endpoint. Flow:

  1. Backend resolves parcel_id -> block_subgraph via
     SpacetimeAtlasService.GetBlockSubgraph (RustyRed).
  2. Backend calls TheseusBridge.GetBatchSpacetimeEmbeddings on the
     subgraph's node_ids.
  3. Backend POSTs the assembled tensor to this Ray Serve endpoint.
  4. This endpoint loads the production model (or staging if flagged),
     runs the CivicPairformerBuildingHead, decodes per-part field
     distributions.
  5. Returns a ReconstructionSpec with every populated field carrying
     `from_gnn_prior=true` and `gnn_version=<model version>`.

The promotion ladder is staging -> production with manual confirm.
This endpoint reads the slot pointer from S3 metadata, not from a
hard-coded path, so a promote operation flips slots without redeploy.

Run:
    serve run civic_atlas_ingest.building_head_infer:building_head_app
    ray job submit --working-dir . -- python -m civic_atlas_ingest.building_head_infer \
        s3://civic-atlas/staging/predict-1.npz

Environment:
    MODEL_SLOT          'staging' or 'production' (default production)
    S3_BUCKET           defaults to civic-atlas
"""

from __future__ import annotations

import os
import sys
from typing import Any, Literal

from fastapi import FastAPI
from ray import serve

from .runtime import ensure_ray_initialized

ModelSlot = Literal["staging", "production"]
http_app = FastAPI(title="Civic Atlas Building Head")


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


def health(slot: ModelSlot = "production") -> dict[str, Any]:
    """Check that a model slot has a loadable artifact."""
    return {
        "slot": slot,
        "status": "stub",
        "note": "Phase 6 inference is a stub. Health check not yet wired.",
    }


@serve.deployment(
    name="civic-atlas-building-head",
    ray_actor_options={"num_cpus": 2, "num_gpus": 1},
)
@serve.ingress(http_app)
class BuildingHeadDeployment:
    """HTTP ingress for Pairformer prior inference."""

    @http_app.post("/predict")
    def predict_endpoint(self, payload: dict[str, Any]) -> dict[str, Any]:
        return predict(payload)

    @http_app.get("/health")
    def health_endpoint(self, slot: ModelSlot = "production") -> dict[str, Any]:
        return health(slot)


building_head_app = BuildingHeadDeployment.bind()


def main(tensor_uri: str = "") -> None:
    """Local entrypoint for direct local smoke runs."""
    if not tensor_uri:
        print("Pass --tensor-uri s3://...")
        return
    ensure_ray_initialized()
    result = predict(
        {
            "block_subgraph_tensor_uri": tensor_uri,
            "model_slot": os.environ.get("MODEL_SLOT", "production"),
            "tenant_id": "flint",
        }
    )
    print(result)


_BUCKET = os.environ.get("S3_BUCKET", "civic-atlas")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
