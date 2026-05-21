# Civic Pairformer Port

The Atlas building head now owns a local Pairformer model module:
`civic_atlas_ingest/building_head_pairformer.py`.

This is a copy-and-adapt port of the Theseus Pairformer architecture, not a
move. Theseus keeps its GNN for epistemic graph work. Atlas gets a separate
model artifact, trained through Ray on RunPod and promoted through the
`civic-atlas-ingest` CLI lane.

## Why Port Instead of Call Theseus Directly?

A gRPC call to Theseus is still useful for frozen spacetime embeddings, and can
remain a fallback inference provider. It should not be the primary building-head
runtime because Atlas needs:

- Civic relation types, not Theseus epistemic edge types.
- Atlas-specific training, evaluation, and promotion gates.
- Tenant isolation and corpus-only training invariants.
- Reproducible model artifacts in the Atlas S3 model ladder.
- Decoder heads that map directly into `ReconstructionSpec` parts.

The boundary should be:

1. Atlas backend assembles a block subgraph.
2. Theseus bridge optionally supplies 256d spacetime embeddings.
3. `civic-atlas-ingest` trains/serves the civic Pairformer building head.
4. Atlas backend persists the returned priors as versioned, source-backed specs.

## Ported Shape

- `CivicPairUpdate`: gated residual edge update.
- `CivicConfidenceHead`: per-edge reliability score.
- `CivicGraphTransformerLayer`: local R-GCN + block-local self-attention.
- `CivicPairformerEncoder`: co-evolves building nodes and civic edges.
- `CivicPartDecoder`: produces categorical and regression outputs for
  `ReconstructionSpec` fields.
- `CivicPairformerBuildingHead`: encoder plus part decoders.

## Civic Adaptations

- Relation vocabulary is small and civic-specific:
  `adjacent_to`, `fronts_street`, `same_block_as`, `anchored_by`,
  temporal predecessor/successor, similarity, shared party wall, shared setback,
  and shared cornice line.
- Attention is block-local. When PyG batches multiple block graphs, one block
  cannot attend into another.
- Pair updates include the current edge representation in the gate input. This
  preserves raw civic relation semantics while still allowing edge refinement.
- Part decoders are explicit and inspectable, so field-level confidence and
  calibration can map back into `ReconstructionSpec`.

## Next Implementation Step

Wire `civic_atlas_ingest/building_head_train.py` to:

1. Load corpus and tenant correction tensors.
2. Build PyG block batches with `focus_node_idx`.
3. Train `CivicPairformerBuildingHead` with masked-field losses.
4. Save `model.pt`, `model_card.json`, decoder vocabularies, and evaluation
   reports under `s3://civic-atlas/models/building_head/<version>/`.
