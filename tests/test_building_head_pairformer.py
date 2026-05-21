from __future__ import annotations

import pytest

from civic_atlas_ingest import building_head_pairformer as pairformer


def test_pairformer_model_card_describes_civic_relation_space() -> None:
    card = pairformer.pairformer_model_card()

    assert card["architecture"] == "civic_pairformer_building_head"
    assert card["source"] == "ported_from_theseus_pairformer"
    assert "adjacent_to" in card["relation_types"]
    assert "shares_cornice_line" in card["relation_types"]
    assert "facade_material" in card["part_categories"]


def test_require_torch_geometric_has_clear_failure_without_ml_stack() -> None:
    if pairformer._TORCH_AVAILABLE and pairformer._PYG_AVAILABLE:
        return

    with pytest.raises(RuntimeError, match="torch and torch-geometric"):
        pairformer.require_torch_geometric()


@pytest.mark.skipif(
    not (pairformer._TORCH_AVAILABLE and pairformer._PYG_AVAILABLE),
    reason="PyTorch and PyG are optional local dependencies",
)
def test_civic_pairformer_forward_shapes() -> None:
    import torch

    config = pairformer.CivicPairformerConfig(
        node_dim=16,
        edge_dim=8,
        hidden=32,
        num_layers=2,
        num_heads=4,
        max_attention_nodes=64,
    )
    model = pairformer.CivicPairformerBuildingHead(config)

    x = torch.randn(8, config.node_dim)
    edge_index = torch.tensor(
        [
            [0, 1, 1, 2, 4, 5, 5, 6],
            [1, 0, 2, 1, 5, 4, 6, 5],
        ],
        dtype=torch.long,
    )
    edge_type = torch.randint(0, config.num_relations, (edge_index.size(1),))
    edge_attr = torch.randn(edge_index.size(1), config.edge_dim)
    batch = torch.tensor([0, 0, 0, 0, 1, 1, 1, 1], dtype=torch.long)
    focus_node_idx = torch.tensor([1, 5], dtype=torch.long)

    output = model(
        x,
        edge_index,
        edge_type,
        edge_attr,
        batch=batch,
        focus_node_idx=focus_node_idx,
        tenant_context="flint",
    )

    assert output.tenant_context == "flint"
    assert output.pairformer.tenant_context == "flint"
    assert output.pairformer.node_embeddings.shape == (8, config.hidden)
    assert output.pairformer.edge_scores.shape == (edge_index.size(1),)
    assert output.pairformer.edge_confidence.shape == (edge_index.size(1),)
    assert output.pairformer.graph_embeddings.shape == (2, config.hidden)
    assert output.part_logits["facade_material"].shape == (
        2,
        len(config.part_categories["facade_material"]),
    )
    assert output.part_values["height_meters"].shape == (2, 2)
    assert torch.all(output.pairformer.edge_confidence >= 0.0)
    assert torch.all(output.pairformer.edge_confidence <= 1.0)


@pytest.mark.skipif(
    not (pairformer._TORCH_AVAILABLE and pairformer._PYG_AVAILABLE),
    reason="PyTorch and PyG are optional local dependencies",
)
def test_tenant_context_is_noop_until_adapters_load() -> None:
    import torch

    torch.manual_seed(42)
    config = pairformer.CivicPairformerConfig(
        node_dim=8,
        edge_dim=4,
        hidden=16,
        num_layers=1,
        num_heads=4,
        dropout=0.0,
    )
    model = pairformer.CivicPairformerBuildingHead(config)
    model.eval()

    x = torch.randn(4, config.node_dim)
    edge_index = torch.tensor([[0, 1, 2], [1, 2, 3]], dtype=torch.long)
    edge_type = torch.randint(0, config.num_relations, (edge_index.size(1),))
    edge_attr = torch.randn(edge_index.size(1), config.edge_dim)
    focus_node_idx = torch.tensor([1], dtype=torch.long)

    base_output = model(
        x,
        edge_index,
        edge_type,
        edge_attr,
        focus_node_idx=focus_node_idx,
        tenant_context=pairformer.DEFAULT_TENANT_CONTEXT,
    )
    flint_output = model(
        x,
        edge_index,
        edge_type,
        edge_attr,
        focus_node_idx=focus_node_idx,
        tenant_context="flint",
    )

    assert flint_output.tenant_context == "flint"
    assert flint_output.pairformer.tenant_context == "flint"
    assert torch.allclose(
        base_output.pairformer.node_embeddings,
        flint_output.pairformer.node_embeddings,
    )
    assert torch.allclose(
        base_output.part_logits["facade_material"],
        flint_output.part_logits["facade_material"],
    )


@pytest.mark.skipif(
    not (pairformer._TORCH_AVAILABLE and pairformer._PYG_AVAILABLE),
    reason="PyTorch and PyG are optional local dependencies",
)
def test_civic_pair_update_preserves_edge_shape() -> None:
    import torch

    update = pairformer.CivicPairUpdate(hidden=12, edge_dim=5)
    h = torch.randn(4, 12)
    edge_index = torch.tensor([[0, 1, 2], [1, 2, 3]], dtype=torch.long)
    edge_attr = torch.randn(3, 5)

    out = update(h, edge_index, edge_attr)

    assert out.shape == edge_attr.shape
