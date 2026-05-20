"""Modal app: train the building head.

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
    modal deploy modal/building_head_train.py
    modal run modal/building_head_train.py::train \
        --run-name pretraining-2026-05-18 \
        --stage pretrain
    modal run modal/building_head_train.py::train \
        --run-name finetune-flint-2026-05-18 \
        --stage finetune \
        --warm-start pretraining-2026-05-18

Environment:
    CIVIC_ATLAS_GRPC_URL        Atlas backend (for corpus + tenant data)
    THESEUS_BRIDGE_GRPC_URL     Theseus bridge (for embeddings)
    CIVIC_ATLAS_TRAIN_TOKEN     bearer token with read scope on corpus + Flint
    S3_BUCKET                   defaults to civic-atlas
"""

from __future__ import annotations

import os
from typing import Any, Literal

import modal

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install(
        "torch>=2.4",
        "torch-geometric>=2.5",
        "torch-sparse>=0.6.18",
        "torch-scatter>=2.1.2",
        "numpy>=1.26",
        "scipy>=1.13",
        "pandas>=2.1",
        "scikit-learn>=1.5",
        "grpcio>=1.65",
        "protobuf>=5.27",
        "matplotlib>=3.9",
        "boto3>=1.35",
        "wandb>=0.17",
        "tqdm>=4.66",
    )
)

app = modal.App("civic-atlas-building-head-train", image=image)


Stage = Literal["pretrain", "finetune"]


@app.function(
    gpu="A10G",
    timeout=60 * 60 * 12,
    cpu=4,
    memory=32768,
    secrets=[
        modal.Secret.from_name("civic-atlas-train"),
        modal.Secret.from_name("civic-atlas-aws"),
        modal.Secret.from_name("civic-atlas-wandb"),
    ],
)
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


@app.function(
    cpu=2,
    memory=4096,
    secrets=[modal.Secret.from_name("civic-atlas-aws")],
)
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


@app.local_entrypoint()
def main(
    run_name: str = "",
    stage: str = "pretrain",
    warm_start: str | None = None,
) -> None:
    """Local entrypoint for `modal run`."""
    if not run_name:
        print("Pass --run-name <id>")
        return
    if stage not in ("pretrain", "finetune"):
        print(f"--stage must be pretrain|finetune, got {stage!r}")
        return
    result = train.remote(run_name=run_name, stage=stage, warm_start=warm_start)
    print(result)


_BUCKET = os.environ.get("S3_BUCKET", "civic-atlas")
