"""Ray Train-compatible task: train the building head.

Pipeline:
  1. Frozen encoder: DyGFormer in Theseus, accessed via
     TheseusBridge.GetBatchSpacetimeEmbeddings. NOT retrained here.
     (Embeddings are precomputed and cached per record.)
  2. Trainable head: CivicPairformerBuildingHead over each building's
     block subgraph (PyTorch Geometric). Nodes and civic relationship
     edges co-evolve; attention is block-local to avoid batched
     cross-block leakage.
  3. Per-part decoder heads: one MLP per part type. Discrete fields
     get a softmax over the field's vocabulary; continuous fields
     get a regression head with Gaussian NLL.

Loss: masked-field prediction.
  - Each forward pass produces logits + regression values for the
    focus node's 5 categorical + 3 regression heads.
  - Targets come from the TrainingCorpusRecord.part_labels.
  - Fields with missing labels are masked out (loss = 0 for those).
  - Each target loss is weighted by coverage_quality so noisy
    Sanborn rows contribute less than clean photo-based rows.

Outputs:
  - Model artifact at s3://civic-atlas/models/building_head/<version>/
    or artifacts/models/<version>/ for local dev runs
  - metrics.json + checkpoint.pt at the same prefix
  - Both timestamped + git-sha-stamped

Run modes:
  - `python -m civic_atlas_ingest.building_head_train <run_name> shape-test --local`
      Synthetic data; validates training-loop shapes without a corpus.
  - `python -m civic_atlas_ingest.building_head_train <run_name> pretrain --corpus path/to/records.jsonl`
      Train on a real TrainingCorpusRecord JSONL.
  - Ray cluster: `ray job submit --working-dir . -- python -m ...`

Environment:
    CIVIC_ATLAS_GRPC_URL        Atlas backend (for corpus + tenant data)
    THESEUS_BRIDGE_GRPC_URL     Theseus bridge (for embeddings)
    CIVIC_ATLAS_TRAIN_TOKEN     bearer token with read scope on corpus + Flint
    S3_BUCKET                   defaults to civic-atlas
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .runtime import ensure_ray_initialized, ray

Stage = Literal["pretrain", "finetune", "shape-test"]


@dataclass(frozen=True)
class TrainConfig:
    run_name: str
    stage: Stage
    max_epochs: int = 50
    batch_size: int = 8  # blocks per gradient step
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    log_every: int = 25
    val_every: int = 5  # epochs
    seed: int = 42
    corpus_path: str | None = None  # JSONL of TrainingCorpusRecord rows
    output_root: str = "artifacts/models"
    warm_start: str | None = None  # pretraining run name to load weights from


@ray.remote(num_cpus=4, num_gpus=1, memory=32 * 1024 * 1024 * 1024)
def train(
    run_name: str,
    stage: Stage,
    *,
    warm_start: str | None = None,
    max_epochs: int = 50,
    batch_size: int = 8,
    corpus_path: str | None = None,
    output_root: str = "artifacts/models",
    learning_rate: float = 1e-3,
) -> dict[str, Any]:
    """Ray-decorated wrapper. The training logic lives in
    `_train_impl` so unit tests can call it without ray.init()."""
    config = TrainConfig(
        run_name=run_name,
        stage=stage,
        max_epochs=max_epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        corpus_path=corpus_path,
        output_root=output_root,
        warm_start=warm_start,
    )
    return _train_impl(config)


def _train_impl(config: TrainConfig) -> dict[str, Any]:
    """Pure-function training loop. Returns a metrics summary."""
    try:
        import torch
        from torch.optim import AdamW
    except ImportError as exc:
        raise RuntimeError(
            "Pairformer training requires torch; install the .[ml] extras "
            "or run inside the Ray training image."
        ) from exc

    from .building_head_pairformer import (
        CivicPairformerBuildingHead,
        CivicPairformerConfig,
        count_parameters,
    )

    if config.stage == "finetune" and not config.warm_start:
        raise ValueError("finetune stage requires --warm-start <pretrain run name>")

    torch.manual_seed(config.seed)
    model_config = CivicPairformerConfig()
    model = CivicPairformerBuildingHead(model_config)
    optimizer = AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )

    output_dir = Path(config.output_root) / config.run_name
    output_dir.mkdir(parents=True, exist_ok=True)

    if config.warm_start:
        warm_path = Path(config.output_root) / config.warm_start / "checkpoint.pt"
        if warm_path.exists():
            state = torch.load(warm_path, map_location="cpu")
            model.load_state_dict(state["model"])
            print(f"  loaded warm-start from {warm_path}", flush=True)

    # Build the training set: synthetic blocks for shape-test mode,
    # real corpus blocks otherwise.
    train_blocks, val_blocks = _build_blocks(config, model_config)
    print(
        f"  training on {len(train_blocks)} blocks ({len(val_blocks)} validation); "
        f"model has {count_parameters(model):,} trainable parameters",
        flush=True,
    )

    metrics_log: list[dict[str, Any]] = []
    best_val_loss = float("inf")
    best_epoch = -1

    for epoch in range(config.max_epochs):
        model.train(True)  # set training mode (dropout, batchnorm running stats)
        epoch_loss = 0.0
        steps = 0
        for batch_start in range(0, len(train_blocks), config.batch_size):
            batch = train_blocks[batch_start : batch_start + config.batch_size]
            loss = _compute_batch_loss(model, batch, model_config)
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            epoch_loss += float(loss.item())
            steps += 1
        avg_train_loss = epoch_loss / max(1, steps)

        if (epoch + 1) % config.val_every == 0 or epoch == config.max_epochs - 1:
            model.train(False)  # switch to inference mode for validation
            with torch.no_grad():
                val_loss = sum(
                    float(_compute_batch_loss(model, [block], model_config).item())
                    for block in val_blocks
                ) / max(1, len(val_blocks))
            metrics_log.append(
                {"epoch": epoch + 1, "train_loss": avg_train_loss, "val_loss": val_loss}
            )
            print(
                f"  epoch {epoch + 1:>3}: train_loss={avg_train_loss:.4f} "
                f"val_loss={val_loss:.4f}",
                flush=True,
            )
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_epoch = epoch + 1
                _save_checkpoint(model, output_dir / "checkpoint.pt", config, model_config)

    # Final checkpoint regardless of val improvement, for resumability.
    _save_checkpoint(model, output_dir / "final.pt", config, model_config)

    summary = {
        "run_name": config.run_name,
        "stage": config.stage,
        "best_epoch": best_epoch,
        "best_val_loss": best_val_loss,
        "final_train_loss": metrics_log[-1]["train_loss"] if metrics_log else None,
        "model_parameters": count_parameters(model),
        "artifact_uri": str(output_dir / "checkpoint.pt"),
        "metrics_log_uri": str(output_dir / "metrics.json"),
        "warm_start": config.warm_start,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    (output_dir / "metrics.json").write_text(
        json.dumps({"summary": summary, "log": metrics_log}, indent=2)
    )
    return summary


def _build_blocks(
    config: TrainConfig,
    model_config: Any,
) -> tuple[list[Any], list[Any]]:
    """Construct training and validation block subgraphs.

    In `shape-test` mode: generate synthetic blocks with random
    features + random labels. The loss won't converge to anything
    meaningful (no real signal), but the loop runs.

    In `pretrain` / `finetune` modes: load TrainingCorpusRecord rows
    from the JSONL corpus, group them into blocks by spatial
    proximity (currently: simple per-record blocks; multi-building
    grouping is the v0.2 path once we have enough records to make
    block context meaningful).
    """
    from .block_subgraph import build_block_subgraph, synthetic_block_subgraph

    if config.stage == "shape-test":
        train_set = [synthetic_block_subgraph(num_buildings=5, config=model_config, seed=i)
                     for i in range(32)]
        val_set = [synthetic_block_subgraph(num_buildings=5, config=model_config, seed=1000 + i)
                   for i in range(8)]
        return train_set, val_set

    if not config.corpus_path:
        raise ValueError(
            f"stage={config.stage} requires --corpus path/to/records.jsonl"
        )
    records = _load_corpus_records(Path(config.corpus_path))
    if not records:
        raise ValueError(f"corpus at {config.corpus_path!r} produced zero records")

    # v0.1: each record becomes its own single-building block.
    # v0.2: group records by spatial proximity into multi-building blocks.
    blocks = [build_block_subgraph([record], config=model_config) for record in records]

    # 80/20 split, deterministic.
    split = max(1, int(0.8 * len(blocks)))
    return blocks[:split], blocks[split:]


def _load_corpus_records(path: Path) -> list[Any]:
    """Read TrainingCorpusRecord rows back from a JSONL produced by
    write_training_batch. Rebuilds the dataclass shape just enough
    for the block-subgraph assembler."""
    from types import SimpleNamespace

    records: list[Any] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            # The assembler reads .record_id, .source, .source_id,
            # .observed_at, .geometry, .extra, .archetype_label,
            # .part_labels. Build a namespace that quacks like
            # TrainingCorpusRecord without re-running the factory.
            records.append(
                SimpleNamespace(
                    record_id=payload["record_id"],
                    source=payload["source"],
                    source_id=payload["source_id"],
                    observed_at=payload.get("observed_at", ""),
                    geometry=payload.get("geometry", {}),
                    archetype_label=payload.get("archetype_label", ""),
                    part_labels=payload.get("part_labels", {}),
                    extra=payload.get("extra", {}),
                )
            )
    return records


def _compute_batch_loss(
    model: Any,
    blocks: list[Any],
    model_config: Any,
) -> Any:
    """Forward + masked-field-prediction loss over a list of blocks.

    Categorical fields: cross-entropy on the focus node's logits
    against the target index, zeroed by the field's mask.

    Regression fields: Gaussian NLL on (mu, log_sigma) output against
    the target value, zeroed by the field's mask.
    """
    import torch
    import torch.nn.functional as F

    total = torch.tensor(0.0, dtype=torch.float32)
    n_active_terms = 0

    for block in blocks:
        out = model(
            block.x,
            block.edge_index,
            block.edge_type,
            block.edge_attr,
            batch=block.batch,
            focus_node_idx=block.focus_node_idx,
        )

        for field, logits in out.part_logits.items():
            target = block.part_targets.get(field)
            mask = block.part_target_masks.get(field)
            if target is None or mask is None or not bool(mask.any()):
                continue
            ce = F.cross_entropy(logits, target, reduction="none")
            masked_ce = (ce * mask.float()).sum()
            n_active = int(mask.sum().item())
            if n_active > 0:
                total = total + masked_ce
                n_active_terms += n_active

        for field, params in out.part_values.items():
            target = block.part_value_targets.get(field)
            mask = block.part_target_masks.get(field)
            if target is None or mask is None or not bool(mask.any()):
                continue
            mu = params[..., 0]
            log_sigma = params[..., 1].clamp(min=-5.0, max=5.0)
            sigma2 = torch.exp(2 * log_sigma)
            # Gaussian NLL: 0.5 * log(2π σ²) + 0.5 * (x - μ)² / σ²
            nll = 0.5 * (math.log(2 * math.pi) + 2 * log_sigma + (target - mu) ** 2 / sigma2)
            masked_nll = (nll * mask.float()).sum()
            n_active = int(mask.sum().item())
            if n_active > 0:
                total = total + masked_nll
                n_active_terms += n_active

    if n_active_terms == 0:
        # No active labels — return a zero scalar with grad path
        # preserved so autograd doesn't crash.
        return total.requires_grad_(True)
    return total / n_active_terms


def _save_checkpoint(
    model: Any,
    path: Path,
    config: TrainConfig,
    model_config: Any,
) -> None:
    """Write a model checkpoint + minimal config snapshot."""
    import torch

    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model": model.state_dict(),
            "model_config": {
                "node_dim": model_config.node_dim,
                "edge_dim": model_config.edge_dim,
                "hidden": model_config.hidden,
                "num_layers": model_config.num_layers,
                "num_heads": model_config.num_heads,
                "dropout": model_config.dropout,
            },
            "train_config": {
                "run_name": config.run_name,
                "stage": config.stage,
                "max_epochs": config.max_epochs,
                "batch_size": config.batch_size,
                "learning_rate": config.learning_rate,
                "seed": config.seed,
            },
            "saved_at": datetime.now(UTC).isoformat(),
        },
        path,
    )


@ray.remote(num_cpus=2, memory=4 * 1024 * 1024 * 1024)
def report_metrics(run_name: str, *, output_root: str = "artifacts/models") -> dict[str, Any]:
    """Load a run's metrics.json and return the parsed summary.

    Lightweight v0.1: reads the file written by `_train_impl`. v0.2
    work: per-part accuracy on a held-out test split, calibration
    plots, 20-building spot-checks.
    """
    path = Path(output_root) / run_name / "metrics.json"
    if not path.exists():
        raise FileNotFoundError(f"no metrics.json at {path}")
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Train the civic Pairformer building head")
    parser.add_argument("run_name", nargs="?", default="")
    parser.add_argument(
        "stage",
        nargs="?",
        default="shape-test",
        choices=["pretrain", "finetune", "shape-test"],
    )
    parser.add_argument("--warm-start", default=None)
    parser.add_argument("--max-epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--corpus", default=None, help="Path to TrainingCorpusRecord JSONL")
    parser.add_argument("--output-root", default="artifacts/models")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run _train_impl directly without ray.init() (for smoke tests).",
    )
    args = parser.parse_args(argv)

    if not args.run_name:
        print("Pass <run_name>. Try: <name> shape-test --local --max-epochs 10")
        return

    config = TrainConfig(
        run_name=args.run_name,
        stage=args.stage,
        max_epochs=args.max_epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        corpus_path=args.corpus,
        output_root=args.output_root,
        warm_start=args.warm_start,
    )

    if args.local:
        result = _train_impl(config)
    else:
        ensure_ray_initialized()
        result = ray.get(
            train.remote(
                run_name=args.run_name,
                stage=args.stage,
                warm_start=args.warm_start,
                max_epochs=args.max_epochs,
                batch_size=args.batch_size,
                corpus_path=args.corpus,
                output_root=args.output_root,
                learning_rate=args.learning_rate,
            )
        )
    print(json.dumps(result, indent=2))


_BUCKET = os.environ.get("S3_BUCKET", "civic-atlas")


if __name__ == "__main__":
    main(sys.argv[1:])
