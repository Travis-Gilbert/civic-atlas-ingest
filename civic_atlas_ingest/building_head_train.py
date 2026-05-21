"""Ray Train-compatible task: train the building head.

Status: skeleton. Real training loop pending finalization of the
ReconstructionSpec part schema. The skeleton wires up the data
loading + frozen-encoder access via Theseus bridge so that loop
can land cleanly when the schema is final.

Architecture (per Phase 6 spec, updated to the civic Pairformer port):
  1. Frozen encoder: DyGFormer in Theseus, accessed via
     TheseusBridge.GetBatchSpacetimeEmbeddings. NOT retrained here.
  2. Trainable head: CivicPairformerBuildingHead over each building's
     block subgraph (PyTorch Geometric). Nodes and civic relationship
     edges co-evolve; attention is block-local to avoid batched
     cross-block leakage.
  3. Per-part decoder heads: one MLP per part type. Discrete fields
     get a softmax over the field's vocabulary; continuous fields
     get a regression head with Gaussian NLL.

Proto field mapping for the decoder outputs (one head per part):
  Mass         -> ReconstructionSpec.mass
                  (form, story_count, height/width/depth)
  Facade       -> ReconstructionSpec.facades[]
                  (orientation, material, color, opening_grids[])
  Roof         -> ReconstructionSpec.roof
                  (form, material, pitch_degrees)
  Ornament     -> ReconstructionSpec.ornaments[]
                  (kind, location, material)
  GroundFloor  -> ReconstructionSpec.ground_floor
                  (use_type, storefront_type, entry_location, has_awning)

Every decoded field is wrapped in a PartProvenance with
`from_gnn_prior=true` and `gnn_version=<run_name>:<short_sha>` so the
inspectability story remains end-to-end auditable.
  4. Loss: masked-field prediction. Mask a random subset of fields
     per record, ask the head to predict them, score against ground
     truth weighted by `coverage_quality`.
  5. Two-pass training:
     - Pre-training on the full corpus tenant (10 cities)
     - Fine-tuning on Flint corrections + hand-encoded specs

Outputs:
  - Model artifact at s3://civic-atlas/models/building_head/<version>/
  - Evaluation report at same prefix
  - Both timestamped + git-sha-stamped

Run:
    ray job submit --working-dir . -- python -m civic_atlas_ingest.building_head_train \
        pretraining-2026-05-18 pretrain
    ray job submit --working-dir . -- python -m civic_atlas_ingest.building_head_train \
        finetune-flint-2026-05-18 finetune pretraining-2026-05-18

Environment:
    CIVIC_ATLAS_GRPC_URL        Atlas backend (for corpus + tenant data)
    THESEUS_BRIDGE_GRPC_URL     Theseus bridge (for embeddings)
    CIVIC_ATLAS_TRAIN_TOKEN     bearer token with read scope on corpus + Flint
    S3_BUCKET                   defaults to civic-atlas
"""

from __future__ import annotations

import os
import sys
from typing import Any, Literal

from .runtime import ensure_ray_initialized, ray

Stage = Literal["pretrain", "finetune"]


@ray.remote(num_cpus=4, num_gpus=1, memory=32 * 1024 * 1024 * 1024)
def train(
    run_name: str,
    stage: Stage,
    *,
    warm_start: str | None = None,
    max_epochs: int = 50,
    batch_size: int = 64,
) -> dict[str, Any]:
    """Train the building head.

    `stage='pretrain'` runs over the corpus tenant.
    `stage='finetune'` runs over Flint corrections + hand-encoded specs.
    Fine-tuning requires `warm_start` to point at a pretraining run.

    Returns { 'run_name', 'stage', 'best_epoch', 'best_val_loss',
              'artifact_uri', 'report_uri' }.
    """
    if stage == "finetune" and warm_start is None:
        raise ValueError("finetune requires --warm-start <pretrain run name>")

    raise NotImplementedError(
        "Phase 6 stub. Civic Pairformer model module is present; "
        "training loop lands after:\n"
        "  - ReconstructionSpec.Part schema is final (Phase 2)\n"
        "  - GetBatchSpacetimeEmbeddings ships in Theseus bridge\n"
        "  - corpus tenant has > 50,000 BuildingPresence records\n"
        f"run_name={run_name}, stage={stage}, warm_start={warm_start}, "
        f"max_epochs={max_epochs}, batch_size={batch_size}"
    )


@ray.remote(num_cpus=2, memory=4 * 1024 * 1024 * 1024)
def evaluate(run_name: str) -> dict[str, Any]:
    """Compute the evaluation report for a trained model.

    Report contents per Phase 6 spec:
      - Per-part accuracy table (one row per part_type)
      - Per-field calibration plot (predicted confidence vs actual correctness)
      - 20-building spot-check side-by-sides
      - Diff vs prior production model

    Output: report.json + report.html at the model's S3 prefix.
    """
    raise NotImplementedError(
        f"Phase 6 stub. Evaluation pending training implementation. run_name={run_name}"
    )


def main(
    run_name: str = "",
    stage: str = "pretrain",
    warm_start: str | None = None,
) -> None:
    """Local entrypoint for `ray job submit` or direct local smoke runs."""
    if not run_name:
        print("Pass --run-name <id>")
        return
    if stage not in ("pretrain", "finetune"):
        print(f"--stage must be pretrain|finetune, got {stage!r}")
        return
    ensure_ray_initialized()
    result = ray.get(train.remote(run_name=run_name, stage=stage, warm_start=warm_start))
    print(result)


_BUCKET = os.environ.get("S3_BUCKET", "civic-atlas")


if __name__ == "__main__":
    main(
        run_name=sys.argv[1] if len(sys.argv) > 1 else "",
        stage=sys.argv[2] if len(sys.argv) > 2 else "pretrain",
        warm_start=sys.argv[3] if len(sys.argv) > 3 else None,
    )
