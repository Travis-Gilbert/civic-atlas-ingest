"""Civic Atlas Pairformer building-head modules.

This is the Atlas-side port of the Theseus Pairformer idea: node and edge
representations co-evolve, but the relation vocabulary and decoder heads are
specific to block-coherent building reconstruction rather than epistemic edges.

The module deliberately avoids importing the Modal SDK. Training, inference,
and any future gRPC shim should import this module as plain model code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_TORCH_AVAILABLE = False
_PYG_AVAILABLE = False

try:
    import torch
    import torch.nn as nn
    from torch_geometric.nn import RGCNConv

    _TORCH_AVAILABLE = True
    _PYG_AVAILABLE = True
except ImportError:
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    RGCNConv = None  # type: ignore[assignment]


CIVIC_RELATION_TYPES: tuple[str, ...] = (
    "adjacent_to",
    "fronts_street",
    "same_block_as",
    "anchored_by",
    "temporal_predecessor_of",
    "temporal_successor_of",
    "similar_to",
    "shares_party_wall",
    "shares_setback_line",
    "shares_cornice_line",
)

DEFAULT_TENANT_CONTEXT = "_base"


DEFAULT_PART_CATEGORIES: dict[str, tuple[str, ...]] = {
    "mass_form": ("rectangular", "l_shaped", "u_shaped", "irregular"),
    "story_count": ("one", "two", "three", "four_plus"),
    "facade_material": ("brick", "wood", "stone", "concrete", "terra_cotta", "unknown"),
    "roof_form": ("flat", "gable", "hip", "mansard", "shed", "unknown"),
    "ground_floor_use": ("residential", "storefront", "industrial", "civic", "unknown"),
}


DEFAULT_PART_REGRESSIONS: tuple[str, ...] = (
    "height_meters",
    "bay_count",
    "roof_pitch_degrees",
)


@dataclass(frozen=True)
class CivicPairformerConfig:
    """Shape knobs for the Atlas building-head Pairformer."""

    node_dim: int = 320
    edge_dim: int = 48
    hidden: int = 128
    num_relations: int = len(CIVIC_RELATION_TYPES)
    num_layers: int = 3
    num_heads: int = 4
    dropout: float = 0.1
    max_attention_nodes: int = 256
    default_tenant_context: str = DEFAULT_TENANT_CONTEXT
    relation_types: tuple[str, ...] = CIVIC_RELATION_TYPES
    part_categories: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_PART_CATEGORIES)
    )
    part_regressions: tuple[str, ...] = DEFAULT_PART_REGRESSIONS


def require_torch_geometric() -> None:
    """Raise a clear error when the optional ML stack is not installed."""
    if not (_TORCH_AVAILABLE and _PYG_AVAILABLE):
        raise RuntimeError(
            "Civic Pairformer requires torch and torch-geometric. "
            "Install the ML dependencies or run inside the Modal training image."
        )


if _TORCH_AVAILABLE and _PYG_AVAILABLE:

    @dataclass
    class CivicPairformerOutput:
        node_embeddings: torch.Tensor
        edge_scores: torch.Tensor
        graph_embeddings: torch.Tensor
        edge_confidence: torch.Tensor
        edge_attr: torch.Tensor
        tenant_context: str

    @dataclass
    class CivicBuildingHeadOutput:
        pairformer: CivicPairformerOutput
        part_logits: dict[str, torch.Tensor]
        part_values: dict[str, torch.Tensor]
        tenant_context: str

    class CivicPairUpdate(nn.Module):
        """Gated residual edge update for civic block relationships."""

        def __init__(self, hidden: int, edge_dim: int):
            super().__init__()
            pair_dim = hidden * 2 + edge_dim
            self.update = nn.Linear(pair_dim, edge_dim)
            self.gate = nn.Linear(pair_dim, edge_dim)
            self.norm = nn.LayerNorm(edge_dim)

        def forward(
            self,
            h: torch.Tensor,
            edge_index: torch.Tensor,
            edge_attr: torch.Tensor,
        ) -> torch.Tensor:
            src, dst = edge_index
            pair_repr = torch.cat([h[src], h[dst], edge_attr], dim=-1)
            update = self.update(pair_repr)
            gate = torch.sigmoid(self.gate(pair_repr))
            return self.norm(edge_attr + gate * update)

    class CivicConfidenceHead(nn.Module):
        """Predict per-edge reliability after node/edge co-evolution."""

        def __init__(self, hidden: int, edge_dim: int, dropout: float):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(hidden * 2 + edge_dim, hidden),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(hidden, 1),
                nn.Sigmoid(),
            )

        def forward(
            self,
            h: torch.Tensor,
            edge_index: torch.Tensor,
            edge_attr: torch.Tensor,
        ) -> torch.Tensor:
            src, dst = edge_index
            features = torch.cat([h[src], h[dst], edge_attr], dim=-1)
            return self.net(features).squeeze(-1)

    class CivicGraphTransformerLayer(nn.Module):
        """Block-local GPS layer with Pairformer edge updates."""

        def __init__(self, config: CivicPairformerConfig):
            super().__init__()
            num_bases = min(4, config.num_relations)
            self.max_attention_nodes = config.max_attention_nodes
            self.local_conv = RGCNConv(
                config.hidden,
                config.hidden,
                config.num_relations,
                num_bases=num_bases,
            )
            self.attn = nn.MultiheadAttention(
                config.hidden,
                config.num_heads,
                dropout=config.dropout,
                batch_first=True,
            )
            self.attn_norm = nn.LayerNorm(config.hidden)
            self.ffn = nn.Sequential(
                nn.Linear(config.hidden, config.hidden * 4),
                nn.GELU(),
                nn.Dropout(config.dropout),
                nn.Linear(config.hidden * 4, config.hidden),
                nn.Dropout(config.dropout),
            )
            self.ffn_norm = nn.LayerNorm(config.hidden)
            self.pair_update = CivicPairUpdate(config.hidden, config.edge_dim)

        def _attend_by_block(
            self,
            h: torch.Tensor,
            batch: torch.Tensor | None,
        ) -> torch.Tensor:
            if h.size(0) > self.max_attention_nodes:
                return torch.zeros_like(h)
            if batch is None:
                attended, _ = self.attn(h.unsqueeze(0), h.unsqueeze(0), h.unsqueeze(0))
                return attended.squeeze(0)

            out = torch.zeros_like(h)
            for graph_id in torch.unique(batch, sorted=True):
                mask = batch == graph_id
                segment = h[mask]
                if segment.numel() == 0:
                    continue
                attended, _ = self.attn(
                    segment.unsqueeze(0),
                    segment.unsqueeze(0),
                    segment.unsqueeze(0),
                )
                out[mask] = attended.squeeze(0)
            return out

        def forward(
            self,
            h: torch.Tensor,
            edge_index: torch.Tensor,
            edge_type: torch.Tensor,
            edge_attr: torch.Tensor,
            *,
            batch: torch.Tensor | None = None,
        ) -> tuple[torch.Tensor, torch.Tensor]:
            local_out = self.local_conv(h, edge_index, edge_type)
            attn_out = self._attend_by_block(h, batch)
            h = self.attn_norm(h + local_out + attn_out)
            h = self.ffn_norm(h + self.ffn(h))
            edge_attr = self.pair_update(h, edge_index, edge_attr)
            return h, edge_attr

    class CivicPairformerEncoder(nn.Module):
        """Pairformer encoder for hydrated Atlas block subgraphs."""

        def __init__(self, config: CivicPairformerConfig | None = None):
            super().__init__()
            self.config = config or CivicPairformerConfig()
            self.node_encoder = nn.Linear(self.config.node_dim, self.config.hidden)
            self.layers = nn.ModuleList(
                [CivicGraphTransformerLayer(self.config) for _ in range(self.config.num_layers)]
            )
            self.edge_predictor = nn.Sequential(
                nn.Linear(self.config.hidden * 2 + self.config.edge_dim, self.config.hidden),
                nn.ReLU(),
                nn.Dropout(self.config.dropout),
                nn.Linear(self.config.hidden, 1),
            )
            self.confidence_head = CivicConfidenceHead(
                self.config.hidden,
                self.config.edge_dim,
                self.config.dropout,
            )
            self.graph_readout = nn.Sequential(
                nn.Linear(self.config.hidden, self.config.hidden),
                nn.ReLU(),
                nn.Linear(self.config.hidden, self.config.hidden),
            )

        def _pool_graphs(
            self,
            h: torch.Tensor,
            batch: torch.Tensor | None,
        ) -> torch.Tensor:
            if batch is None:
                return self.graph_readout(h.mean(dim=0, keepdim=True))

            num_graphs = int(batch.max().item()) + 1 if batch.numel() else 0
            pooled = torch.zeros((num_graphs, h.size(-1)), dtype=h.dtype, device=h.device)
            counts = torch.zeros((num_graphs, 1), dtype=h.dtype, device=h.device)
            pooled.index_add_(0, batch, h)
            counts.index_add_(
                0,
                batch,
                torch.ones((h.size(0), 1), dtype=h.dtype, device=h.device),
            )
            return self.graph_readout(pooled / counts.clamp(min=1.0))

        def forward(
            self,
            x: torch.Tensor,
            edge_index: torch.Tensor,
            edge_type: torch.Tensor,
            edge_attr: torch.Tensor,
            *,
            batch: torch.Tensor | None = None,
            tenant_context: str = DEFAULT_TENANT_CONTEXT,
        ) -> CivicPairformerOutput:
            h = self.node_encoder(x).relu()
            e = edge_attr

            for layer in self.layers:
                h, e = layer(h, edge_index, edge_type, e, batch=batch)

            src, dst = edge_index
            edge_features = torch.cat([h[src], h[dst], e], dim=-1)
            edge_scores = self.edge_predictor(edge_features).squeeze(-1)
            edge_confidence = self.confidence_head(h, edge_index, e)
            graph_embeddings = self._pool_graphs(h, batch)
            return CivicPairformerOutput(
                node_embeddings=h,
                edge_scores=edge_scores,
                graph_embeddings=graph_embeddings,
                edge_confidence=edge_confidence,
                edge_attr=e,
                tenant_context=tenant_context,
            )

    class CivicPartDecoder(nn.Module):
        """Per-part decoder heads for focus building nodes."""

        def __init__(
            self,
            hidden: int,
            categories: dict[str, tuple[str, ...]],
            regressions: tuple[str, ...],
            dropout: float,
        ):
            super().__init__()
            self.categories = categories
            self.regressions = regressions
            self.categorical_heads = nn.ModuleDict(
                {
                    field_name: nn.Sequential(
                        nn.Linear(hidden, hidden),
                        nn.ReLU(),
                        nn.Dropout(dropout),
                        nn.Linear(hidden, len(values)),
                    )
                    for field_name, values in categories.items()
                }
            )
            self.regression_heads = nn.ModuleDict(
                {
                    field_name: nn.Sequential(
                        nn.Linear(hidden, hidden),
                        nn.ReLU(),
                        nn.Dropout(dropout),
                        nn.Linear(hidden, 2),
                    )
                    for field_name in regressions
                }
            )

        def forward(
            self,
            node_embeddings: torch.Tensor,
            focus_node_idx: torch.Tensor | None = None,
            *,
            tenant_context: str = DEFAULT_TENANT_CONTEXT,
        ) -> tuple[dict[str, torch.Tensor], dict[str, torch.Tensor]]:
            _ = tenant_context
            focus = node_embeddings if focus_node_idx is None else node_embeddings[focus_node_idx]
            logits = {name: head(focus) for name, head in self.categorical_heads.items()}
            values = {name: head(focus) for name, head in self.regression_heads.items()}
            return logits, values

    class CivicPairformerBuildingHead(nn.Module):
        """Atlas building head: Pairformer encoder plus ReconstructionSpec decoders."""

        def __init__(self, config: CivicPairformerConfig | None = None):
            super().__init__()
            self.config = config or CivicPairformerConfig()
            self.encoder = CivicPairformerEncoder(self.config)
            self.decoder = CivicPartDecoder(
                self.config.hidden,
                self.config.part_categories,
                self.config.part_regressions,
                self.config.dropout,
            )

        def forward(
            self,
            x: torch.Tensor,
            edge_index: torch.Tensor,
            edge_type: torch.Tensor,
            edge_attr: torch.Tensor,
            *,
            batch: torch.Tensor | None = None,
            focus_node_idx: torch.Tensor | None = None,
            tenant_context: str = DEFAULT_TENANT_CONTEXT,
        ) -> CivicBuildingHeadOutput:
            pairformer = self.encoder(
                x,
                edge_index,
                edge_type,
                edge_attr,
                batch=batch,
                tenant_context=tenant_context,
            )
            part_logits, part_values = self.decoder(
                pairformer.node_embeddings,
                focus_node_idx=focus_node_idx,
                tenant_context=tenant_context,
            )
            return CivicBuildingHeadOutput(
                pairformer=pairformer,
                part_logits=part_logits,
                part_values=part_values,
                tenant_context=tenant_context,
            )


def pairformer_model_card(config: CivicPairformerConfig | None = None) -> dict[str, Any]:
    """Return architecture metadata without requiring a trained checkpoint."""
    config = config or CivicPairformerConfig()
    return {
        "architecture": "civic_pairformer_building_head",
        "source": "ported_from_theseus_pairformer",
        "node_dim": config.node_dim,
        "edge_dim": config.edge_dim,
        "hidden": config.hidden,
        "num_layers": config.num_layers,
        "num_heads": config.num_heads,
        "num_relations": config.num_relations,
        "default_tenant_context": config.default_tenant_context,
        "relation_types": list(config.relation_types),
        "part_categories": {key: list(values) for key, values in config.part_categories.items()},
        "part_regressions": list(config.part_regressions),
        "torch_available": _TORCH_AVAILABLE,
        "pyg_available": _PYG_AVAILABLE,
    }


def count_parameters(model: Any) -> int:
    """Count trainable parameters for reports and health probes."""
    return sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)
